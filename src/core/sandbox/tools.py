"""暴露给 agent 的沙箱工具。

三条硬规则（违反任意一条都是安全事故）：

1. **scope_id 从 runtime context 取，不从工具入参取** —— 工具参数由 LLM
   生成，模型可以被诱导传入他人的 user_id。
2. **所有异常脱敏后返回** —— 详细错误进日志，返回给模型的只有简短中文。
3. **有硬超时** —— 沙箱里的死循环不能拖住整个请求。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from langchain.tools import tool
from langchain_core.tools import ToolException
from opensandbox.exceptions.sandbox import SandboxException

from core.context_type import get_runtime_context
from core.sandbox.file_links import get_sandbox_file_link
from core.sandbox.registry import get_sandbox_manager
from core.sandbox.runtime import execute_python
from core.sandbox.sessions import import_session_file
from core.security import redact, safe_error_message
from core.utils.logging import get_logger

logger = get_logger(__name__)

# service 使用标准 logging，与工具日志保持相同级别。
logging.getLogger("core.sandbox").setLevel(logging.INFO)

__all__ = ["SANDBOX_TOOLS", "get_sandbox_environment", "run_python"]

#: 单次命令的硬超时（秒）：模型跑飞时不能把整轮对话拖住。
_COMMAND_TIMEOUT_SECONDS = 30

_UNAVAILABLE = "代码执行沙箱暂不可用（未配置或服务未就绪），请联系管理员。"


def _scope_id() -> str | None:
    """从运行时上下文取权限范围键。

    返回 ``None`` 表示拿不到调用者身份 —— 此时**必须拒绝执行**。
    """
    ctx = get_runtime_context()
    if ctx is None or not ctx.user_id:
        return None
    # 组织 + 用户，保证跨组织同名用户不串沙箱
    return f"{ctx.tenant_id}:{ctx.user_id}"


def _write_permission() -> str | None:
    """检查调用者是否有权使用沙箱。返回拒绝原因，``None`` 表示放行。"""
    ctx = get_runtime_context()
    if ctx is None:
        return "无法识别调用者身份，已拒绝执行。"
    if not ctx.can("read"):
        return "当前账号没有使用沙箱的权限。"
    return None


# 固定只读脚本，不接受模型代码或路径，避免把任意执行伪装成免审批查询。
_ENVIRONMENT_CODE = """import json, os, platform
cwd = os.getcwd()
entries = sorted(os.listdir(cwd))
print(json.dumps({"environment": "opensandbox", "platform": platform.system(),
    "cwd": cwd, "entries": entries[:100], "truncated": len(entries) > 100}, ensure_ascii=False))
"""


@tool
def get_sandbox_environment() -> str:
    """只读查询当前用户 OpenSandbox 的操作系统、实际当前目录和目录文件列表。

    不查看宿主机，不读取文件内容或环境变量；用于回答当前工作空间或沙箱环境问题。
    """
    denied = _write_permission()
    if denied is not None:
        raise ToolException(denied)
    scope = _scope_id()
    if scope is None:
        raise ToolException("无法识别调用者身份，已拒绝查询。")
    manager = get_sandbox_manager()
    if manager is None:
        raise ToolException(_UNAVAILABLE)
    context = get_runtime_context()
    thread_id = str(context.extra.get("approval_thread_id", ""))

    def _work() -> str:
        execution = execute_python(context, thread_id, _ENVIRONMENT_CODE, 10)
        if execution["exit_code"] != 0:
            raise ToolException("沙箱环境查询失败，未获得目录信息。")
        # 仅接受固定脚本的结构化结果，不把无关日志当作环境描述。
        return json.dumps(json.loads(execution["stdout"]), ensure_ascii=False)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_work).result(timeout=20)
    except FutureTimeout:
        raise ToolException("沙箱环境查询超时，请稍后重试。") from None
    except (SandboxException, OSError, ValueError) as exc:
        logger.exception("sandbox.environment.failed", error=redact(str(exc)))
        raise ToolException(f"沙箱环境查询失败：{safe_error_message(exc)}") from exc


@tool
def run_python(code: str, timeout_seconds: int = 20) -> dict[str, Any]:
    """在隔离沙箱里执行一段 Python 代码并返回输出。

    适用于：跑数据计算、验证算法、处理小段文本。**不要**用它执行
    耗时超过几分钟的任务，也不要用它访问外网或写入生产系统。

    每次调用使用当前登录用户专属的沙箱，代码不能看到其他用户的数据。
    当前工作目录可写，请使用相对路径，如 dissertation/ch1.txt；/workspace 根目录只读。
    每次调用启动独立进程，变量不会保留，分批内容必须保存为当前目录中的文件。
    返回 state（success/error）、data（stdout/stderr/exit_code）、error（失败原因）。

    Args:
        code: 要执行的 Python 源码。
        timeout_seconds: 期望的超时秒数（实际受服务端硬上限约束）。

    """
    result = _run_python(code, timeout_seconds)
    if isinstance(result, str):
        return {"state": "error", "data": None, "error": result}
    ok = result["exit_code"] == 0 and not result["error"]
    return {
        "state": "success" if ok else "error",
        "data": {key: result[key] for key in ("stdout", "stderr", "exit_code")},
        "error": "" if ok else str(result["error"] or f"Python 退出码 {result['exit_code']}"),
    }


def _run_python(code: str, timeout_seconds: int) -> dict[str, Any] | str:
    denied = _write_permission()
    if denied is not None:
        return denied

    scope = _scope_id()
    if scope is None:
        return "无法识别调用者身份，已拒绝执行。"

    manager = get_sandbox_manager()
    if manager is None:
        return _UNAVAILABLE

    if not isinstance(code, str) or not code.strip():
        return "code 不能为空。"
    limit = max(5, min(int(timeout_seconds or 20), _COMMAND_TIMEOUT_SECONDS))
    context = get_runtime_context()
    thread_id = str(context.extra.get("approval_thread_id", ""))

    logger.info("sandbox.run_python", scope=scope, code_len=len(code), limit=limit)

    def _work() -> dict[str, Any]:
        result = execute_python(context, thread_id, code, limit)
        result["stdout"] = result["stdout"][-4000:]
        result["stderr"] = result["stderr"][-2000:]
        return result

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_work)
            out = future.result(timeout=limit + 10)
    except FutureTimeout:
        logger.warning("sandbox.timeout", scope=scope, limit=limit)
        return f"执行超时（{limit} 秒）。请简化代码后重试。"
    except Exception as exc:
        logger.exception("sandbox.run_python.failed", error=redact(str(exc)))
        return f"沙箱执行失败：{safe_error_message(exc)}"

    # 即使执行失败也要把 stdout / stderr 带回去 —— 语法错误、异常堆栈
    # 都只出现在 stderr 里，丢掉的话模型无从修正代码。
    return out


# 由服务端声明只读，不能由模型或外部工具描述修改。
get_sandbox_environment.metadata = {"approval_mode": "read_only"}
run_python.metadata = {"approval_mode": "sandbox_execution"}

#: 供 core.agent 直接展开
SANDBOX_TOOLS: tuple[Any, ...] = (
    get_sandbox_environment,
    run_python,
    import_session_file,
    get_sandbox_file_link,
)
