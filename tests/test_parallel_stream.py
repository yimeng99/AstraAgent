from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

from api import chat_execution
from api.stream_events import wants_tool_event
from core.context_type import MemoryContext


@pytest.mark.asyncio
async def test_parallel_subagents_do_not_reset_main_reasoning_parser(monkeypatch):
    def event(kind, run, parents=(), name="model", content=None):
        data = {"input": {}} if content is None else {"chunk": AIMessageChunk(content=content)}
        if kind == "on_tool_end":
            data = {"output": ToolMessage(content="子任务交接结果", tool_call_id=run)}
        elif kind == "on_chat_model_end":
            data = {"output": AIMessage(content="", id=run)}
        return {
            "event": kind,
            "run_id": run,
            "parent_ids": list(parents),
            "name": name,
            "data": data,
            "tags": [],
            "metadata": {},
        }

    events = [
        event("on_chat_model_start", "main"),
        event("on_chat_model_stream", "main", content="<thi"),
        event("on_tool_start", "task-a", name="task"),
        event("on_tool_start", "task-b", name="task"),
        event("on_chat_model_start", "child-a", ["root", "task-a", "nested"]),
        event("on_chat_model_stream", "child-a", ["task-a"], content="<think>章节七180"),
        event("on_chat_model_start", "child-b", ["task-b"]),
        event("on_chat_model_stream", "child-b", ["task-b"], content="章节八</think>"),
        event("on_chat_model_stream", "child-a", ["task-a"], content="0字</think>子任务正文"),
        event("on_chat_model_end", "child-a", ["task-a"]),
        event("on_chat_model_end", "child-b", ["task-b"]),
        event("on_tool_end", "task-a", name="task"),
        event("on_tool_end", "task-b", name="task"),
        event("on_chat_model_stream", "main", content="nk>主任务思考</think>主任务正文"),
        event("on_chat_model_end", "main"),
    ]

    async def stream(*args, **kwargs):
        for item in events:
            yield item

    observed = []
    monkeypatch.setattr(chat_execution, "stream_once", stream)
    monkeypatch.setattr(chat_execution.SubagentRecorder, "save", AsyncMock())
    monkeypatch.setattr(chat_execution.Collector, "start", AsyncMock())
    monkeypatch.setattr(chat_execution.Collector, "report", AsyncMock(return_value=None))
    monkeypatch.setattr(
        chat_execution.Collector, "observe", lambda self, item: observed.append(item)
    )
    graph = StateGraph(MessagesState, context_schema=MemoryContext)
    graph.add_node("model", lambda state: {})
    graph.add_edge(START, "model")
    graph.add_edge("model", END)
    result = [
        item
        async for item in chat_execution.stream_agent_events(
            agent=graph.compile(checkpointer=InMemorySaver()),
            user_input="test",
            user_text="test",
            thread_id="alice-12345678",
            include_tool_events=True,
            context=MemoryContext(user_id="alice"),
        )
    ]
    assert (
        "".join(item["delta"] for item in result if item["type"] == "message.delta") == "主任务正文"
    )
    assert (
        "".join(item["delta"] for item in result if item["type"] == "reasoning.delta")
        == "主任务思考"
    )
    assert sum(item["type"] == "assistant.start" for item in result) == 1
    assert sum(item["type"] == "tool.end" for item in result) == 2
    assert wants_tool_event(True, "write_file")
    assert len(observed) == len(events)
    assert not any(item["type"] == "done" for item in result)
