"""环境查询失败不能被流式事件或历史回放标成成功。"""

import pytest
from langchain_core.tools import ToolException

from api.utils.messages import tool_result_failed
from core.context_type import MemoryContext
from core.sandbox import tools


def test_environment_timeout_is_tool_error(monkeypatch):
    context = MemoryContext(
        user_id="alice",
        permissions=frozenset({"read"}),
        extra={"approval_thread_id": "alice-12345678"},
    )
    monkeypatch.setattr(tools, "get_runtime_context", lambda: context)
    monkeypatch.setattr(tools, "get_sandbox_manager", lambda: object())

    def timeout(*args):
        raise TimeoutError("connect timed out")

    monkeypatch.setattr(tools, "execute_python", timeout)
    with pytest.raises(ToolException, match="沙箱环境查询"):
        tools.get_sandbox_environment.invoke({})


@pytest.mark.parametrize("result", ["沙箱环境查询超时，请稍后重试。", "沙箱环境查询失败：连接超时"])
def test_old_environment_errors_remain_errors(result):
    assert tool_result_failed(result, "get_sandbox_environment")


def test_successful_environment_is_not_error():
    assert not tool_result_failed('{"cwd":"/workspace/sessions/demo"}', "get_sandbox_environment")
