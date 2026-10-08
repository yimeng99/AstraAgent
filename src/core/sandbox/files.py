"""沙箱文件操作；路由只处理 HTTP，SDK 调用与会话边界集中在这里。"""

import json
import shlex
from pathlib import PurePosixPath

from core.context_type import MemoryContext
from core.sandbox.file_reads import read_binary
from core.sandbox.registry import get_sandbox_manager
from core.sandbox.sessions import session_root
from core.sessions import assert_thread_owner


class SandboxFileError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# 只执行固定文件操作，不执行调用方代码。租约将文件操作与模型执行串行化。
_SCRIPT = """import json, os, stat, sys, shutil
root, action, relative, destination = json.loads(sys.argv[1])
try:
    os.makedirs(root, mode=0o700, exist_ok=True)
    if os.path.realpath(root) != root:
        raise PermissionError('会话根目录异常')
    def checked(value):
        path = os.path.normpath(os.path.join(root, value))
        resolved = os.path.realpath(path)
        if resolved != root and not resolved.startswith(root + '/'):
            raise PermissionError('不能访问其他会话或越过工作目录')
        if os.path.islink(path):
            raise PermissionError('不支持操作符号链接')
        return path
    path = checked(relative)
    if action == 'list':
        if not os.path.isdir(path): raise NotADirectoryError('目录不存在')
        entries = []
        visited = 0
        def walk_error(error): raise error
        for directory, folders, files in os.walk(path, followlinks=False, onerror=walk_error):
            folders[:] = [name for name in folders if not os.path.islink(os.path.join(directory, name))]
            visited += len(folders) + len(files)
            if visited > 10000: raise ValueError('会话文件过多，暂时无法列出')
            for name in files:
                filename = os.path.join(directory, name)
                if os.path.islink(filename): continue
                info = os.stat(checked(os.path.relpath(filename, root)), follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode): continue
                entries.append(dict(name=name, path=os.path.relpath(filename, root),
                    directory=False, size=info.st_size, modified_at=info.st_mtime))
                if len(entries) > 1000: raise ValueError('会话文件超过 1000 项，请先清理不需要的文件')
        output = dict(entries=sorted(entries, key=lambda x:(x['name'].casefold(), x['path'])))
    elif action == 'read':
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode): raise ValueError('只能下载普通文件')
        if info.st_size > 20*1024*1024: raise OverflowError('单个文件不能超过 20 MiB')
        output = dict(size=info.st_size)
    elif action == 'upload':
        if os.path.lexists(path): raise FileExistsError('同名文件已存在，请先重命名')
        if not os.path.isdir(os.path.dirname(path)): raise FileNotFoundError('目标目录不存在')
        output = {}
    elif action == 'mkdir':
        if path == root: raise ValueError('请指定新文件夹名称')
        os.mkdir(path, mode=0o700)
        output = {}
    elif action == 'rename':
        if path == root: raise ValueError('不能重命名会话根目录')
        target = checked(destination)
        if os.path.lexists(target): raise FileExistsError('同名文件已存在')
        os.rename(path, target)
        output = {}
    elif action == 'delete':
        if path == root: raise ValueError('不能删除会话根目录')
        if os.path.isdir(path): shutil.rmtree(path)
        else: os.unlink(path)
        output = {}
    else: raise ValueError('未知文件操作')
    print(json.dumps(dict(ok=True, **output), ensure_ascii=False))
except Exception as error:
    status = 404 if isinstance(error, (FileNotFoundError, NotADirectoryError)) else 409 if isinstance(error, FileExistsError) else 403 if isinstance(error, PermissionError) else 413 if isinstance(error, OverflowError) else 400
    print(json.dumps(dict(ok=False, status=status, detail=str(error)), ensure_ascii=False))
"""


def _command(sandbox, root: str, action: str, path: str, destination: str = "") -> dict:
    arguments = json.dumps([root, action, path, destination], ensure_ascii=False)
    result = sandbox.commands.run(
        "python3 -c " + shlex.quote(_SCRIPT) + " " + shlex.quote(arguments)
    )
    if result.exit_code != 0:
        raise RuntimeError("沙箱文件服务执行失败")
    output = "".join(item.text for item in result.logs.stdout)
    payload = json.loads(output)
    if not payload["ok"]:
        raise SandboxFileError(payload["status"], payload["detail"])
    return payload


def _validate_access(context: MemoryContext, thread_id: str, paths) -> None:
    assert_thread_owner(thread_id, context.user_id)
    if context.user_id == "anonymous" or not context.can("read"):
        raise SandboxFileError(403, "当前用户无法访问工作空间")
    for value in paths:
        if (
            value.startswith("/")
            or ".." in PurePosixPath(value).parts
            or any(c in value for c in ("\\", "\0"))
        ):
            raise SandboxFileError(400, "请使用当前会话内的相对路径")


def read_session_files(
    context: MemoryContext, thread_id: str, paths: list[str], *, max_bytes: int
) -> list[bytes]:
    """整批文件只获取一次租约，避免每章重新连接、恢复沙箱和检查 skills。"""
    _validate_access(context, thread_id, paths)
    manager = get_sandbox_manager()
    if manager is None:
        raise SandboxFileError(503, "沙箱暂不可用")
    root = session_root(thread_id)
    remaining = max_bytes
    contents = []
    with manager.acquire(context, wait=True) as sandbox:
        for path in paths:
            payload = _command(sandbox, root, "read", path)
            if payload["size"] > remaining:
                raise OverflowError(f"章节文本总大小超过 {max_bytes} 字节，请分卷生成")
            data = read_binary(sandbox, root + "/" + path, max_bytes=remaining)
            if len(data) != payload["size"]:
                raise RuntimeError("沙箱文件读取不完整")
            remaining -= len(data)
            contents.append(data)
    return contents


def operate_file(
    context: MemoryContext,
    thread_id: str,
    action: str,
    path: str,
    *,
    destination: str = "",
    data: bytes | None = None,
    max_bytes: int = 20 * 1024 * 1024,
):
    _validate_access(context, thread_id, (path, destination))
    if data is not None and len(data) > 20 * 1024 * 1024:
        raise OverflowError("文件超过 20 MiB")
    manager = get_sandbox_manager()
    if manager is None:
        raise SandboxFileError(503, "沙箱暂不可用")
    root = session_root(thread_id)
    # 文件面板与代码执行共享租约，检查和读写必须在同一次租约内完成。
    with manager.acquire(context, wait=True) as sandbox:
        payload = _command(sandbox, root, action, path, destination)
        if action == "read":
            content = read_binary(sandbox, root + "/" + path, max_bytes=max_bytes)
            if len(content) != payload["size"]:
                raise RuntimeError("沙箱文件读取不完整")
            return content
        if action == "upload":
            sandbox.files.write_file(root + "/" + path, data or b"")
        return payload
