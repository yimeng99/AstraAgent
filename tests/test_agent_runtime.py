"""验证生命周期、工具失败和模型重试的边界。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import ToolException, tool
from langgraph.errors import GraphInterrupt
from langgraph.prebuilt.tool_node import ToolCallRequest
from openai import APITimeoutError

import core.agent as core_agent
from core.model_retry import model_timeout_retry
from core.tool_errors import ToolErrorMiddleware


@pytest.mark.parametrize("stage", ["sandbox", "checkpointer", "mcp", "build"])
async def test_failed_startup_closes_resources(monkeypatch, stage):
    failure = RuntimeError("startup failed")
    sandbox = Mock(side_effect=failure if stage == "sandbox" else None)
    checkpointer = AsyncMock(side_effect=failure if stage == "checkpointer" else None)
    mcp = AsyncMock(side_effect=failure if stage == "mcp" else None, return_value=[])
    build = Mock(side_effect=failure if stage == "build" else None)
    close = AsyncMock()
    monkeypatch.setattr("core.sandbox.registry.init_sandbox", sandbox)
    monkeypatch.setattr("core.checkpointer.init_checkpointer", checkpointer)
    monkeypatch.setattr("core.mcp.registry.init_mcp", mcp)
    monkeypatch.setattr(core_agent, "build_core_agent", build)
    monkeypatch.setattr(core_agent, "close_agent_resources", close)

    with pytest.raises(RuntimeError, match="startup failed"):
        async with core_agent.core_lifespan(SimpleNamespace()):
            pytest.fail("Startup failure must not yield an agent")

    close.assert_awaited_once()


@pytest.mark.parametrize("failed", ["business", "mcp", "ragwiki", "store", "checkpointer"])
async def test_one_close_failure_does_not_leak_other_resources(monkeypatch, failed):
    closed = []

    def close(name):
        closed.append(name)
        if name == failed:
            raise RuntimeError(f"{name} close failed")

    async def close_async(name):
        close(name)

    monkeypatch.setattr(core_agent, "shutdown_mcp", lambda: close_async("mcp"))
    monkeypatch.setattr("core.checkpointer.close_checkpointer", lambda: close_async("checkpointer"))
    monkeypatch.setattr("ragwiki.client.close_ragwiki_client", lambda: close_async("ragwiki"))
    monkeypatch.setattr("core.backend.close_store", lambda: close("store"))
    monkeypatch.setattr("core.sandbox.registry.shutdown_sandbox", lambda: close("sandbox"))
    monkeypatch.setattr(
        "business.discover_business",
        lambda: SimpleNamespace(bundles=[SimpleNamespace(close=lambda: close_async("business"))]),
    )

    with pytest.raises(RuntimeError, match=f"{failed} close failed"):
        await core_agent.close_agent_resources()

    assert closed == ["business", "mcp", "ragwiki", "store", "checkpointer", "sandbox"]


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.parametrize(
    "failure", [TypeError("broken implementation"), ToolException("not found")]
)
async def test_graph_distinguishes_programming_error_from_tool_failure(failure):
    @tool
    async def lookup() -> str:
        """Look up a resource."""
        raise failure

    graph = create_agent(
        ToolModel(
            responses=[
                AIMessage(
                    content="", tool_calls=[{"id": "lookup-1", "name": "lookup", "args": {}}]
                ),
                AIMessage(content="completed"),
            ]
        ),
        tools=[lookup],
        middleware=[ToolErrorMiddleware()],
    )
    if isinstance(failure, TypeError):
        with pytest.raises(TypeError, match="broken implementation"):
            await graph.ainvoke({"messages": [("user", "look up")]})
    else:
        result = await graph.ainvoke({"messages": [("user", "look up")]})
        error = next(message for message in result["messages"] if isinstance(message, ToolMessage))
        assert error.status == "error"
        assert "not found" in error.content
        assert result["messages"][-1].content == "completed"


def tool_request(name="read_file"):
    return ToolCallRequest(
        tool_call={"name": name, "id": "call-1", "args": {}},
        tool=None,
        state={},
        runtime=None,
    )


@pytest.mark.parametrize(
    "failure", [AttributeError(), RuntimeError(), GraphInterrupt(), asyncio.CancelledError()]
)
async def test_control_flow_and_programming_errors_propagate(failure):
    handler = AsyncMock(side_effect=failure)
    with pytest.raises(type(failure)):
        await ToolErrorMiddleware().awrap_tool_call(tool_request(), handler)
    handler.assert_awaited_once()


@pytest.mark.parametrize("name,attempts", [("read_file", 3), ("write_file", 1)])
async def test_only_read_tools_retry_network_failures(monkeypatch, name, attempts):
    sleep = AsyncMock()
    monkeypatch.setattr("core.tool_errors.asyncio.sleep", sleep)
    handler = AsyncMock(side_effect=httpx.ReadTimeout("remote timeout"))

    result = await ToolErrorMiddleware().awrap_tool_call(tool_request(name), handler)

    assert result.status == "error"
    assert handler.await_count == attempts
    assert sleep.await_count == attempts - 1


def test_sync_read_can_succeed_after_transient_failure(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("core.tool_errors.time.sleep", sleep)
    result = ToolMessage(content="ok", tool_call_id="call-1")
    handler = Mock(side_effect=[TimeoutError(), result])

    assert ToolErrorMiddleware().wrap_tool_call(tool_request(), handler) is result
    assert handler.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_model_timeout_retry_uses_exception_types():
    class TimeoutConfigurationError(ValueError):
        pass

    retry = model_timeout_retry("openai")
    assert isinstance(TimeoutError(), retry.retry_on)
    assert isinstance(httpx.ReadTimeout("timeout"), retry.retry_on)
    assert isinstance(
        APITimeoutError(request=httpx.Request("POST", "http://model.test")), retry.retry_on
    )
    assert not isinstance(TimeoutConfigurationError(), retry.retry_on)
    assert retry.on_failure == "error"
