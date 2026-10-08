"""把用户上传的图片同步进沙箱。

上传文件存在**存储后端**（本地磁盘 / OSS），那个路径在容器里不存在 —— 容器是
独立文件系统；所以必须在 agent 用它之前把字节写进容器，并告知容器内路径。

写到当前会话目录的 uploads 子目录；文件名由
服务端生成（不沿用客户端名，杜绝路径穿越）；同一 file_id 重复同步覆盖。同步要
走一次 acquire + 传输，失败返回空列表，由调用方处理降级。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opensandbox.models.filesystem import WriteEntry

from core.sandbox.registry import get_sandbox_manager
from core.sandbox.sessions import check_path, session_root
from core.sessions import assert_thread_owner
from core.storage import StorageError
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger(__name__)

__all__ = ["SandboxAttachment", "sync_attachments_to_sandbox"]

#: 单个文件同步的硬超时（秒）。超过则放弃并降级，不拖住请求。
_SYNC_TIMEOUT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class SandboxAttachment:
    """一个已同步进沙箱的附件。"""

    file_id: str
    #: 容器内绝对路径，agent 在代码里用这个
    sandbox_path: str
    filename: str
    size: int


def _ensure_dir(sandbox, path: str) -> None:
    # 当前 SDK 要求 WriteEntry；dict 会在访问 entry.path 时报错，不再逐个尝试旧接口。
    sandbox.files.create_directories([WriteEntry(path=path, mode=700)])


def sync_attachments_to_sandbox(
    scope: str,
    file_ids: Sequence[str],
    *,
    display_names: dict[str, str] | None = None,
    thread_id: str | None = None,
    context=None,
) -> list[SandboxAttachment]:
    """把宿主机上的附件同步进该 scope 的沙箱。

    Args:
        scope: 权限范围键（``org:user``），来自服务端认证信息。
        file_ids: 已上传文件的 ID 列表。
        display_names: ``file_id -> 原始文件名``，仅用于回执展示。

    Returns:
        同步成功的附件列表。沙箱不可用 / 超时 / 全部失败时返回空列表
        —— **调用方应据此降级，而不是报错**。
    """
    if not file_ids:
        return []
    if context is None or scope != f"{context.tenant_id}:{context.user_id}":
        raise PermissionError("附件同步缺少有效用户上下文")
    if not thread_id:
        logger.warning("sandbox.sync.skipped", reason="缺少会话上下文")
        return []

    manager = get_sandbox_manager()
    if manager is None:
        logger.info("sandbox.sync.skipped", reason="沙箱未就绪", count=len(file_ids))
        return []

    # 在这里 import，避免 api 层直接依赖 core.sandbox 的存储规则
    from api.storage import UploadRejectedError, load_stored_bytes, resolve_stored_key

    # 先在存储侧解析 key（本地是纯文件查询，OSS 是一次列举）；失败的直接剔除
    pending: list[tuple[str, str]] = []
    for fid in file_ids:
        try:
            pending.append((fid, resolve_stored_key(fid)))
        except UploadRejectedError:
            logger.warning("sandbox.sync.stale", file_id=fid)

    if not pending:
        return []

    assert_thread_owner(thread_id, context.user_id)
    root = session_root(thread_id)
    target_dir = f"{root}/uploads"

    def _work() -> list[SandboxAttachment]:
        synced: list[SandboxAttachment] = []
        # 租约用完必须关闭，否则该 scope 的沙箱会被永久标记占用
        with manager.acquire(context, wait=True) as sandbox:
            check_path(sandbox, root, target_dir)
            _ensure_dir(sandbox, target_dir)
            for fid, key in pending:
                name = key.rsplit("/", 1)[-1]  # 已是服务端生成的 {file_id}.{ext}
                remote = f"{target_dir}/{name}"
                try:
                    # 逐个读：某个失败只跳过它，不影响其余附件
                    data = load_stored_bytes(fid)
                except (UploadRejectedError, StorageError):
                    logger.warning("sandbox.sync.read_failed", file_id=fid)
                    continue
                try:
                    check_path(sandbox, root, remote)
                    sandbox.files.write_file(remote, data)
                except Exception:
                    logger.exception("sandbox.sync.write_failed", file_id=fid)
                    continue
                synced.append(
                    SandboxAttachment(
                        file_id=fid,
                        sandbox_path=remote,
                        filename=(display_names or {}).get(fid, name),
                        size=len(data),
                    )
                )
        return synced

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_work)
            result = future.result(timeout=_SYNC_TIMEOUT_SECONDS)
    except FutureTimeout:
        logger.warning("sandbox.sync.timeout", count=len(pending))
        return []
    except Exception:
        logger.exception("sandbox.sync.failed")
        return []

    logger.info(
        "sandbox.sync.ok",
        scope=scope,
        requested=len(pending),
        synced=len(result),
    )
    return result
