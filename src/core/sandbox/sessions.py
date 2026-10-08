"""会话目录与 namespace 执行；不可用时拒绝执行，不回退到容器根环境。"""

from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import PurePosixPath

from langchain.tools import tool
from opensandbox.models.filesystem import WriteEntry
from opensandbox.models.isolated import (
    BindMount,
    CreateIsolatedSessionRequest,
    IsolatedRunOpts,
    IsolatedWorkspaceSpec,
)
from opentelemetry import trace

from core.context_type import get_runtime_context
from core.sandbox.file_reads import read_binary
from core.sandbox.registry import get_sandbox_manager
from core.sandbox.skills import SKILLS_ROOT
from core.sessions import assert_thread_owner
from core.tracing import operation


def session_root(thread_id: str) -> str:
    return "/workspace/sessions/" + hashlib.sha256(thread_id.encode()).hexdigest()


def current_session_root() -> str:
    ctx = get_runtime_context()
    thread = str(ctx.extra.get("approval_thread_id", "")) if ctx else ""
    if not ctx or not thread:
        raise RuntimeError("缺少会话上下文，拒绝访问沙箱")
    assert_thread_owner(thread, ctx.user_id)
    return session_root(thread)


def resolve_path(root: str, path: str) -> str:
    parts = PurePosixPath(path).parts
    if ".." in parts or "\\" in path or "\0" in path:
        raise ValueError("文件路径不能越过会话目录")
    if path == root or path.startswith(root + "/"):
        return str(PurePosixPath(path))
    if path.startswith("/workspace/sessions"):
        raise ValueError("其他会话文件必须通过 import_session_file 授权导入")
    relative = path.removeprefix("/workspace/").lstrip("/")
    return str(PurePosixPath(root) / relative)


def check_path(sandbox, root: str, path: str) -> None:
    # root SDK 不受执行 namespace 约束，必须防止符号链接把写入引向别的会话。
    code = f"import os; r=os.path.realpath({root!r}); p=os.path.realpath({path!r}); assert p==r or p.startswith(r+'/'), 'path escapes session'"
    result = sandbox.commands.run("python3 -c " + shlex.quote(code))
    if result.exit_code != 0:
        raise ValueError("路径或符号链接越过会话目录，访问被拒绝")


@operation("sandbox.execute")
def run_in_session(sandbox, root: str, code: str, timeout: int):
    capabilities = sandbox.isolation.capabilities()
    if not capabilities.available:
        raise RuntimeError(
            "服务端未启用会话 namespace 隔离，已拒绝执行；请管理员调整 OpenSandbox 容器权限"
        )
    sandbox.files.create_directories([WriteEntry(path=root, mode=700)])
    # strict 的根目录仍是只读可见；遮住整个 workspace，再只挂回当前会话。
    # 挂载源必须处于 execd 默认白名单 /workspace 内；遮蔽后自身也不可见。
    mask = "/workspace/.session-masks/" + hashlib.sha256(root.encode()).hexdigest()
    mountpoint = mask + root.removeprefix("/workspace")
    sandbox.files.create_directories(
        [
            WriteEntry(path=mountpoint, mode=755),
            WriteEntry(path=mask + "/skills", mode=755),
        ]
    )
    # SDK 写入的文件属于 root。只移交当前目录，且不沿符号链接修改其他目录。
    prepare = f"""import os
root = {root!r}
assert os.path.realpath(root) == root, 'session root must not be a symlink'
assert os.path.realpath({SKILLS_ROOT!r}) == {SKILLS_ROOT!r}, 'skills root must not be a symlink'
os.chown(root, 1000, 1000, follow_symlinks=False)
os.chmod(root, 0o700)
for directory, directories, files in os.walk(root, followlinks=False):
    for name in directories + files:
        os.chown(os.path.join(directory, name), 1000, 1000, follow_symlinks=False)
"""
    prepared = sandbox.commands.run("python3 -c " + shlex.quote(prepare))
    if prepared.exit_code != 0:
        raise RuntimeError("无法准备当前会话的非 root 执行权限，已拒绝执行")
    request = CreateIsolatedSessionRequest(
        workspace=IsolatedWorkspaceSpec(path=root, mode="rw"),
        profile="strict",
        share_net=False,
        uid=1000,
        gid=1000,
        uid_mode="setpriv",
        binds=[
            BindMount(source=mask, dest="/workspace", readonly=True),
            BindMount(source=root, dest=root, readonly=False),
            # 只共享当前用户容器的技能库，其他会话目录仍被 workspace 掩盖。
            BindMount(source=SKILLS_ROOT, dest=SKILLS_ROOT, readonly=True),
        ],
    )
    with sandbox.isolation.session(request) as session:
        result = session.run(
            "cd -- " + shlex.quote(root) + " && python3 -c " + shlex.quote(code),
            opts=IsolatedRunOpts(timeout_seconds=timeout),
        )
        span = trace.get_current_span()
        if result.exit_code is not None:
            span.set_attribute("sandbox.exit_code", result.exit_code)
            if result.exit_code != 0:
                span.set_status(trace.StatusCode.ERROR)
        return result


@tool
def import_session_file(
    source_thread_id: str, source_path: str, destination_path: str = "imports"
) -> str:
    """经用户审批将同一用户其他会话的指定文件复制到当前会话供读取或编辑。

    不开放其他会话目录；修改导入副本不会修改原文件。
    source_thread_id 必须是目标会话的真实 ID，不得猜测。
    """
    ctx = get_runtime_context()
    if not ctx or not ctx.can("read"):
        return "无法识别调用用户或无访问权限"
    assert_thread_owner(source_thread_id, ctx.user_id)
    root = current_session_root()
    source_root = session_root(source_thread_id)
    source = resolve_path(source_root, source_path)
    destination = resolve_path(root, destination_path)
    destination = str(PurePosixPath(destination) / PurePosixPath(source).name)
    manager = get_sandbox_manager()
    if not manager:
        return "沙箱暂不可用"
    with manager.acquire(ctx, wait=True) as sandbox:
        check_path(sandbox, source_root, source)
        check_path(sandbox, root, destination)
        # 有界读取，防止导入任意大文件耗尽后端内存。
        try:
            data = read_binary(sandbox, source)
        except OverflowError:
            return "文件超过 20 MiB，请选择更小的文件"
        sandbox.files.create_directories(
            [WriteEntry(path=str(PurePosixPath(destination).parent), mode=700)]
        )
        sandbox.files.write_file(destination, data)
    return json.dumps(
        {"imported_path": destination, "source_thread_id": source_thread_id, "mode": "copy"},
        ensure_ascii=False,
    )
