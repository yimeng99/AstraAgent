"""真实 Deep Agents 构图：未启用沙箱时，普通聊天和用户记忆仍可运行。"""

from deepagents.backends.utils import create_file_data
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

import core.agent as core_agent
import core.backend as backend
from core.config import AppConfig
from core.context_type import MemoryContext


class ChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def build_without_sandbox(monkeypatch):
    store = InMemoryStore()
    store.put(("memories", "org", "alice"), "/AGENTS.md", create_file_data("alice preferences"))
    store.put(("memories", "org", "alice"), "/habits.md", create_file_data("alice habits"))
    model = ChatModel(responses=[AIMessage(content="Hello")])
    monkeypatch.setattr(core_agent, "build_llm_client", lambda config: model)
    monkeypatch.setattr(backend, "get_store", lambda: store)
    monkeypatch.setattr("core.sandbox.registry._manager", None)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    graph = core_agent.build_core_agent(AppConfig(), checkpointer=InMemorySaver())
    return graph


async def test_chat_reads_memory_without_sandbox(monkeypatch):
    graph = build_without_sandbox(monkeypatch)
    result = await core_agent.run_once(
        graph,
        "Hello",
        "alice-12345678",
        MemoryContext(user_id="alice", tenant_id="org", permissions=frozenset({"read"})),
    )

    assert result["messages"][-1].content == "Hello"
    state = await graph.aget_state({"configurable": {"thread_id": "alice-12345678"}})
    assert state.values["memory_contents"] == {
        "/memories/AGENTS.md": "alice preferences",
        "/memories/habits.md": "alice habits",
    }
    assert "SkillsMiddleware.before_agent" not in graph.get_graph().nodes


async def test_stream_without_sandbox_keeps_user_memory_isolated(monkeypatch):
    graph = build_without_sandbox(monkeypatch)
    context = MemoryContext(
        user_id="bob",
        tenant_id="org",
        permissions=frozenset({"read"}),
        extra={"approval_thread_id": "bob-12345678"},
    )
    events = [
        event async for event in core_agent.stream_once(graph, "Hello", "bob-12345678", context)
    ]
    result = next(
        event["data"]["output"]
        for event in events
        if event["event"] == "on_chain_end" and not event["parent_ids"]
    )

    assert result["messages"][-1].content == "Hello"
    assert result["memory_contents"] == {}
