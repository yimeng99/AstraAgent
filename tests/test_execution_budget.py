"""真实图验证：循环工具任务在硬上限前收尾，下一轮获得新的预算。"""

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from core.agent import stream_once
from core.context_type import MemoryContext
from core.execution_budget import ExecutionBudgetMiddleware


class LoopModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.parametrize("limit", [25, 125])
async def test_deep_agent_loop_finishes_and_next_turn_resets(limit):
    calls = []

    @tool
    def lookup() -> str:
        """Read a resource."""
        calls.append(1)
        return "resource found"

    # 故意使用无视 tools=[] 的模型，验证错误 provider 也不会继续调用工具。
    graph = create_deep_agent(
        model=LoopModel(
            responses=[
                AIMessage(
                    content="", tool_calls=[{"id": f"lookup-{index}", "name": "lookup", "args": {}}]
                )
                for index in range(200)
            ]
        ),
        tools=[lookup],
        middleware=[ExecutionBudgetMiddleware()],
        checkpointer=InMemorySaver(),
    )
    config = {"recursion_limit": limit, "configurable": {"thread_id": f"budget-{limit}"}}
    first = await graph.ainvoke({"messages": [("user", "keep working")]}, config)
    assert "执行步数上限" in first["messages"][-1].text
    assert not first["messages"][-1].tool_calls
    before = len(calls)
    assert before > 0
    second = await graph.ainvoke({"messages": [("user", "continue")]}, config)
    assert len(calls) > before
    assert not second["messages"][-1].tool_calls
    snapshot = await graph.aget_state(config)
    assert not snapshot.next
    assert "remaining_steps" not in snapshot.values


def test_sync_graph_finishes():
    graph = create_deep_agent(
        model=LoopModel(responses=[AIMessage(content="summary")]),
        middleware=[ExecutionBudgetMiddleware()],
    )
    result = graph.invoke({"messages": [("user", "hello")]}, {"recursion_limit": 25})
    assert result["messages"][-1].content == "summary"


async def test_stream_entry_preserves_configured_limit():
    calls = []

    @tool
    def lookup() -> str:
        """Read a resource."""
        calls.append(1)
        return "found"

    graph = create_deep_agent(
        model=LoopModel(
            responses=[
                AIMessage(
                    content="", tool_calls=[{"id": f"call-{index}", "name": "lookup", "args": {}}]
                )
                for index in range(200)
            ]
        ),
        tools=[lookup],
        middleware=[ExecutionBudgetMiddleware()],
        checkpointer=InMemorySaver(),
    ).with_config({"recursion_limit": 125})
    events = [
        event
        async for event in stream_once(
            graph, "work", "alice-babecafe", MemoryContext(user_id="alice")
        )
    ]
    assert len(calls) > 10
    assert any(event["event"] == "on_chain_end" and not event["parent_ids"] for event in events)
    snapshot = await graph.aget_state({"configurable": {"thread_id": "alice-babecafe"}})
    assert not snapshot.next
    assert "执行步数上限" in snapshot.values["messages"][-1].text
