"""将报表产物写入调用用户的持久沙箱，存储下载副本与可编辑文件分开。"""

from __future__ import annotations

from pathlib import PurePosixPath

from opensandbox.models.filesystem import WriteEntry

from core.context_type import get_runtime_context
from core.sandbox.registry import get_sandbox_manager
from core.sandbox.sessions import check_path, current_session_root, resolve_path


def artifact_path(filename: str, file_id: str, directory: str | None = None) -> str:
    if not filename or filename in (".", "..") or any(c in filename for c in ("/", "\\", "\0")):
        raise ValueError("文件名只能包含名称，目录请通过 sandbox_dir 指定")
    folder = directory if directory is not None else f"/workspace/artifacts/{file_id}"
    path = PurePosixPath(folder)
    if not folder.startswith("/") or ".." in path.parts or "\\" in folder or "\0" in folder:
        raise ValueError("sandbox_dir 必须是沙箱内绝对路径，不能包含路径穿越或 Windows 路径")
    return str(path / filename)


def sync_artifact(data: bytes, path: str) -> str:
    ctx = get_runtime_context()
    if ctx is None or not ctx.user_id or not ctx.can("read"):
        raise RuntimeError("无法识别调用用户或没有使用沙箱的权限")
    manager = get_sandbox_manager()
    if manager is None:
        raise RuntimeError("用户沙箱暂不可用")
    root = current_session_root()
    path = resolve_path(root, path)
    # scope 只来自调用上下文，模型不可以传入其他用户的沙箱标识。
    with manager.acquire(ctx, wait=True) as sandbox:
        check_path(sandbox, root, path)
        sandbox.files.create_directories(
            [WriteEntry(path=str(PurePosixPath(path).parent), mode=755)]
        )
        sandbox.files.write_file(path, data)
        # 回读校验成功才向模型宣告可编辑，避免仅下载副本落库却被当作同步成功。
        if sandbox.files.read_bytes(path) != data:
            raise RuntimeError("沙箱文件回读校验失败")
    return path
