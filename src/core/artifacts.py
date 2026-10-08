"""助手产物（生成的报表/文档）的落库与回传。

「生成报表」最终要落到一个**用户能下载的文件**上。这个模块管三件事：

1. **落库** —— 把渲染好的字节写进存储后端（本地磁盘 / OSS）。key 沿用
   ``{file_id}.{后缀}`` 约定，于是既有的 ``/api/v1/files/{id}`` 下载端点、
   presign、``resolve_stored_key`` 全都不用改就能用。
2. **当轮回传** —— 工具跑在 agent 图里，没有往 SSE 里塞事件的通道。工具把
   产物登记到进程内的待发列表，``api.routes.chat`` 在流结束时取走并推
   ``artifact.created`` 事件。用登记表而不是 LangGraph 的 custom stream，
   是为了不依赖 stream_mode 的细节，且好测。
3. **跨轮持久化** —— 同时按 thread 追加一份 JSON 日志，刷新页面 / 切回会话时
   :mod:`api.history` 能把它挂回最后一条 assistant 消息上。否则文件还在存储
   里，但聊天记录里没有下载入口，用户等于拿不到。
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Final

from core.storage import FILES_URL_PREFIX, StorageError, get_backend
from core.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "Artifact",
    "load_thread_artifacts",
    "save_artifact",
    "take_pending",
]

#: 产物日志的 key 前缀。
#: 注意：本地后端只接受**扁平 key**（``Path(key).name != key`` 直接拒），
#: 所以这里不能用 ``artifacts/xxx.json`` 这种带目录的写法。
_LOG_PREFIX: Final[str] = "artifact-log-"

#: thread_id 会被塞进对象 key，必须当成不可信输入：它上游来自请求头里的
#: user_id（``{user_id}-{8hex}``），不洗就可能有 ``../``。
#: 只留字母数字、下划线、连字符 —— 连点都不留，省得出现 ``..``。
_SAFE_ID: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_\-]")


@dataclass(frozen=True, slots=True)
class Artifact:
    """一个可下载的产物。"""

    file_id: str
    filename: str
    size: int
    content_type: str
    url: str
    #: image | document —— 前端据此决定用预览图还是文件卡片
    kind: str = "document"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Artifact:
        return cls(
            file_id=str(raw.get("file_id", "")),
            filename=str(raw.get("filename", "")),
            size=int(raw.get("size", 0) or 0),
            content_type=str(raw.get("content_type", "")),
            url=str(raw.get("url", "")),
            kind=str(raw.get("kind", "document")),
        )


#: thread_id → 本轮新产生的产物（等 chat.py 取走）
_pending: dict[str, list[Artifact]] = {}
_lock = threading.Lock()


def _safe_thread_id(thread_id: str) -> str:
    return _SAFE_ID.sub("_", thread_id)[:120]


def _log_key(thread_id: str) -> str:
    return f"{_LOG_PREFIX}{_safe_thread_id(thread_id)}.json"


def save_artifact(
    data: bytes,
    *,
    filename: str,
    content_type: str,
    thread_id: str | None = None,
) -> Artifact:
    """把产物字节写进存储，并登记到待发列表 / 线程日志。

    Args:
        data: 文件字节。
        filename: 展示用文件名（含后缀，决定存储 key 的后缀）。
        content_type: MIME。
        thread_id: 会话 ID。给了才会登记回传与持久化。

    Returns:
        :class:`Artifact`。

    Raises:
        core.storage.StorageError: 存储后端不可用。
    """
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    suffix = re.sub(r"[^a-z0-9]", "", suffix)[:8] or "bin"
    file_id = uuid.uuid4().hex
    key = f"{file_id}.{suffix}"

    backend = get_backend()
    backend.put_bytes(key, data, content_type=content_type)

    artifact = Artifact(
        file_id=file_id,
        filename=filename,
        size=len(data),
        content_type=content_type,
        url=f"{FILES_URL_PREFIX}/{file_id}",
        kind="image" if content_type.startswith("image/") else "document",
    )

    if thread_id:
        with _lock:
            _pending.setdefault(thread_id, []).append(artifact)
        _append_to_log(thread_id, artifact)

    logger.info(
        "artifact.saved",
        file_id=file_id,
        filename=filename,
        size=len(data),
        content_type=content_type,
        thread_id=thread_id,
    )
    return artifact


def take_pending(thread_id: str) -> list[Artifact]:
    """取走并清空该 thread 本轮产生的产物（chat.py 收尾时调用）。"""
    with _lock:
        return _pending.pop(thread_id, [])


# ── 线程日志（跨轮） ────────────────────────────────


def _append_to_log(thread_id: str, artifact: Artifact) -> None:
    """把产物追加进 ``artifacts/{thread_id}.json``。

    写失败只记日志：产物本身已经落库、当轮也能回传，不该因为日志写不进去
    就让整轮对话失败。
    """
    key = _log_key(thread_id)
    backend = get_backend()
    existing = _read_log(backend, key)
    existing.append(artifact.to_dict())
    try:
        backend.put_bytes(
            key,
            json.dumps(existing, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )
    except StorageError:
        logger.exception("artifact.log.write_failed", thread_id=thread_id)


def load_thread_artifacts(thread_id: str) -> list[Artifact]:
    """读取该 thread 累积的产物（历史接口用）。"""
    if not thread_id:
        return []
    raw = _read_log(get_backend(), _log_key(thread_id))
    out: list[Artifact] = []
    for item in raw:
        try:
            out.append(Artifact.from_dict(item))
        except Exception:
            logger.warning("artifact.log.bad_entry", thread_id=thread_id)
    return out


def _read_log(backend: Any, key: str) -> list[dict[str, Any]]:
    try:
        if not backend.exists(key):
            return []
        parsed = json.loads(backend.get_bytes(key).decode("utf-8"))
    except (StorageError, ValueError):
        logger.warning("artifact.log.unreadable", key=key)
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]
