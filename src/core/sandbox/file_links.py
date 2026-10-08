"""把已存在的会话文件转换为聊天中可预览、下载的链接。"""

from __future__ import annotations

import json
import shlex
from pathlib import PurePosixPath
from urllib.parse import quote

from langchain.tools import tool

from core.context_type import get_runtime_context
from core.sandbox.registry import get_sandbox_manager
from core.sandbox.sessions import check_path, current_session_root, resolve_path, session_root


def sandbox_file_url(thread_id: str, path: str) -> str:
    root = session_root(thread_id)
    if not path.startswith(root + "/"):
        raise ValueError("文件不属于当前会话")
    relative = path[len(root) + 1 :]
    return f"/api/v1/threads/{quote(thread_id, safe='')}/sandbox/content?path={quote(relative, safe='')}"


@tool
def get_sandbox_file_link(path: str) -> str:
    """验证当前会话的沙箱文件，并返回可直接放进回复的 Markdown 预览、下载链接。

    生成或编辑文件后、用户索要文件地址时调用。不能猜测链接或提供其他会话文件。
    """
    ctx = get_runtime_context()
    if ctx is None or not ctx.can("read"):
        return "无法识别用户或无文件访问权限"
    root = current_session_root()
    path = resolve_path(root, path)
    manager = get_sandbox_manager()
    if manager is None:
        return "沙箱暂不可用"
    # 模型可能并行索取多个文件链接；复用管理器的限时等待，避免同用户的只读校验互相抢占。
    with manager.acquire(ctx, wait=True) as sandbox:
        check_path(sandbox, root, path)
        code = f"import os,stat; p={path!r}; assert not os.path.islink(p); s=os.stat(p); assert stat.S_ISREG(s.st_mode); assert s.st_size<=20*1024*1024"
        result = sandbox.commands.run("python3 -c " + shlex.quote(code))
        if result.exit_code != 0:
            return "文件不存在、不是普通文件或超过 20 MiB，不能提供链接"
    url = sandbox_file_url(str(ctx.extra["approval_thread_id"]), path)
    name = PurePosixPath(path).name.replace("[", "\\[").replace("]", "\\]")
    return json.dumps(
        {"path": path, "markdown": f"[{name}]({url}) · [下载]({url}&download=true)"},
        ensure_ascii=False,
    )


get_sandbox_file_link.metadata = {"approval_mode": "read_only"}
