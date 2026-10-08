"""提供普通 Python 执行结果，工具层不接触 OpenSandbox 的响应对象。"""

from core.context_type import MemoryContext
from core.sandbox.registry import get_sandbox_manager
from core.sandbox.sessions import run_in_session, session_root
from core.sessions import assert_thread_owner


def execute_python(context: MemoryContext, thread_id: str, code: str, timeout: int) -> dict:
    assert_thread_owner(thread_id, context.user_id)
    if not context.can("read"):
        raise PermissionError("当前账号没有使用沙箱的权限")
    manager = get_sandbox_manager()
    if manager is None:
        raise RuntimeError("沙箱暂不可用")
    # 租约必须关闭，否则该范围的沙箱会被永久标记占用。
    with manager.acquire(context, wait=True) as sandbox:
        execution = run_in_session(sandbox, session_root(thread_id), code, timeout)
        # SDK 的 stdout/stderr 在 logs 下，不在响应顶层。
        return {
            "stdout": _as_text(execution.logs.stdout),
            "stderr": _as_text(execution.logs.stderr),
            "exit_code": execution.exit_code,
            # error.value 可能只有退出码；诊断优先使用 stderr。
            "error": _as_text(execution.error),
        }


def _as_text(value: object) -> str:
    """把 SDK 的日志字段统一成字符串。

    实测 ``Execution.logs.stdout`` 是 ``list[OutputMessage]``，每个元素的
    文本在 ``.text`` 上 —— 直接 ``str()`` 会得到 Python repr
    （``[OutputMessage(text='5', ...)]``），必须显式取 ``.text``。
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_as_text(v) for v in value)
    # OutputMessage 等带 .text 的对象
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text
    return str(value)
