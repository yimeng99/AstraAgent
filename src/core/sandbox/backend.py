"""把 Deep Agents 文件工具接到 OpenSandbox 的当前会话目录。"""

from __future__ import annotations

import base64
import json
import shlex
from contextlib import contextmanager

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.sandbox import BaseSandbox

from core.context_type import get_runtime_context
from core.sandbox.registry import get_sandbox_manager
from core.sandbox.sessions import check_path, resolve_path, run_in_session, session_root
from core.sandbox.skills import SKILLS_ROOT
from core.security import safe_error_message
from core.sessions import assert_thread_owner
from core.utils.logging import get_logger

logger = get_logger(__name__)


class _SessionFiles(BaseSandbox):
    """复用框架的分页、搜索和编辑；shell 仅供文件实现调用，不暴露给模型。"""

    def __init__(self, permission: str):
        self.permission = permission
        ctx = get_runtime_context()
        # 与 run_python 一致：会话工作区可写不等于授予外部业务系统的 write 权限。
        if ctx is None or ctx.user_id == "anonymous" or not ctx.can("read"):
            raise PermissionError(f"缺少沙箱 {permission} 权限")
        thread = str(ctx.extra.get("approval_thread_id", ""))
        if not thread:
            raise PermissionError("缺少会话上下文，拒绝访问沙箱")
        assert_thread_owner(thread, ctx.user_id)
        self.scope = f"{ctx.tenant_id}:{ctx.user_id}"
        self.context = ctx
        self.root = session_root(thread)
        self.manager = get_sandbox_manager()
        if self.manager is None:
            raise RuntimeError("沙箱暂不可用")

    @property
    def id(self) -> str:
        return f"{self.scope}:{self.root}"

    def path(self, path: str) -> str:
        if path.rstrip("/") == SKILLS_ROOT or path.startswith(SKILLS_ROOT + "/"):
            if self.permission != "read":
                raise PermissionError("skills 是用户共享的只读目录")
            target = resolve_path(SKILLS_ROOT, path)
            check_path(self.sandbox, SKILLS_ROOT, target)
            return target
        target = resolve_path(self.root, "/" if path == "/workspace" else path)
        check_path(self.sandbox, self.root, target)
        return target

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        # 所有框架生成的命令都走既有 namespace；隔离失败时绝不改用 root 执行。
        code = f"import subprocess; raise SystemExit(subprocess.call({command!r}, shell=True))"
        result = run_in_session(self.sandbox, self.root, code, min(timeout or 30, 60))
        logs = getattr(result, "logs", None)
        # execd 按行返回且去掉换行；直接拼接会破坏 ls 的 JSON Lines 输出。
        output = "".join(
            item.text if item.text.endswith("\n") else item.text + "\n"
            for channel in ("stdout", "stderr")
            for item in (getattr(logs, channel, None) or [])
        )
        return ExecuteResponse(output=output, exit_code=result.exit_code)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results = []
        for path, content in files:
            target = self.path(path)
            if len(content) > 20 * 1024 * 1024:
                results.append(FileUploadResponse(path=path, error="文件超过 20 MiB"))
                continue
            # 二进制传输同样在 namespace 中进行，不能经 root SDK 绕过隔离。
            # 分块避免 execd 日志/命令长度限制截断大文件。
            for offset in range(0, max(len(content), 1), 48 * 1024):
                encoded = base64.b64encode(content[offset : offset + 48 * 1024]).decode()
                code = (
                    "import base64; from pathlib import Path; "
                    f"p=Path({target!r}); p.parent.mkdir(parents=True, exist_ok=True); "
                    f"f=p.open({'wb' if offset == 0 else 'ab'!r}); "
                    f"f.write(base64.b64decode({encoded!r})); f.close()"
                )
                result = self.execute("python3 -c " + shlex.quote(code))
                if result.exit_code != 0:
                    raise RuntimeError("沙箱文件写入失败")
            results.append(FileUploadResponse(path=path))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results = []
        for path in paths:
            target = self.path(path)
            content = bytearray()
            while True:
                code = (
                    "import base64,json; "
                    f"f=open({target!r},'rb'); f.seek({len(content)}); "
                    "chunk=f.read(49152); print(json.dumps({'size':len(chunk),"
                    "'data':base64.b64encode(chunk).decode()})); f.close()"
                )
                result = self.execute("python3 -c " + shlex.quote(code))
                if result.exit_code != 0:
                    results.append(FileDownloadResponse(path=path, error="file_not_found"))
                    break
                chunk = json.loads(result.output)
                decoded = base64.b64decode(chunk["data"], validate=True)
                if len(decoded) != chunk["size"]:
                    raise RuntimeError("沙箱文件传输不完整")
                content.extend(decoded)
                if len(content) > 20 * 1024 * 1024:
                    raise OverflowError("文件超过 20 MiB")
                if len(decoded) < 48 * 1024:
                    results.append(FileDownloadResponse(path=path, content=bytes(content)))
                    break
        return results

    def _edit_via_upload(self, file_path, old_string, new_string, replace_all):
        # 框架大文本编辑默认把临时文件放 /tmp；每次 namespace 的 /tmp 不共享。
        # 改用框架同样提供的内联实现，避免跨执行依赖临时目录。
        return self._edit_inline(file_path, old_string, new_string, replace_all)


@contextmanager
def _session_files(permission: str):
    files = _SessionFiles(permission)
    # 路径校验、分块传输和编辑共用租约，避免检查后被另一操作修改。
    with files.manager.acquire(files.context, wait=True) as sandbox:
        files.sandbox = sandbox
        yield files


class OpenSandboxBackend(BackendProtocol):
    """仅暴露文件协议；身份按每次调用获取，禁止缓存用户上下文。"""

    def ls(self, path):
        try:
            with _session_files("read") as files:
                return files.ls(files.path(path))
        except Exception as exc:
            return LsResult(error=safe_error_message(exc))

    def read(self, file_path, offset=0, limit=2000):
        try:
            with _session_files("read") as files:
                return files.read(files.path(file_path), offset, limit)
        except Exception as exc:
            return ReadResult(error=safe_error_message(exc))

    def grep(self, pattern, path=None, glob=None, *, max_count=None):
        try:
            with _session_files("read") as files:
                return files.grep(pattern, files.path(path or "/"), glob, max_count=max_count)
        except Exception as exc:
            return GrepResult(error=safe_error_message(exc))

    def glob(self, pattern, path=None):
        try:
            with _session_files("read") as files:
                # 绝对 pattern 也必须限制在当前会话，避免绕过搜索目录参数。
                if pattern.startswith("/") or ".." in pattern.split("/") or "\\" in pattern:
                    raise ValueError("glob 请使用当前目录下的相对匹配模式")
                return files.glob(pattern, files.path(path or "/"))
        except Exception as exc:
            return GlobResult(error=safe_error_message(exc))

    def write(self, file_path, content):
        try:
            with _session_files("write") as files:
                return files.write(files.path(file_path), content)
        except Exception as exc:
            logger.exception("sandbox.file.write.failed")
            return WriteResult(
                error=str(exc)
                if isinstance(exc, (PermissionError, ValueError))
                else safe_error_message(exc)
            )

    def edit(self, file_path, old_string, new_string, replace_all=False):
        try:
            with _session_files("write") as files:
                return files.edit(files.path(file_path), old_string, new_string, replace_all)
        except Exception as exc:
            logger.exception("sandbox.file.edit.failed")
            return EditResult(
                error=str(exc)
                if isinstance(exc, (PermissionError, ValueError))
                else safe_error_message(exc)
            )

    def delete(self, file_path):
        with _session_files("write") as files:
            return files.delete(files.path(file_path))

    def upload_files(self, files):
        with _session_files("write") as session:
            return session.upload_files(files)

    def download_files(self, paths):
        with _session_files("read") as session:
            return session.download_files(paths)
