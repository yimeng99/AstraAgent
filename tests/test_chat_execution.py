"""执行边界使用真实 LangGraph 和 SDK 消息验证，不用兼容假对象撑过测试。"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command

from api import chat_execution, run_failures
from api.stream_events import StreamState
from core.artifacts import Artifact
from core.context_type import MemoryContext

THREAD_ID = "alice-12345678"
CONTEXT = MemoryContext(user_id="alice")


@pytest.fixture
def agent():
    model = FakeListChatModel(responses=["<think>思考</think>结果"])

    async def respond(state):
        return {"messages": [await model.ainvoke(state["messages"])]}

    graph = StateGraph(MessagesState, context_schema=MemoryContext)
    graph.add_node("model", respond)
    graph.add_edge(START, "model")
    graph.add_edge("model", END)
    return graph.compile(checkpointer=InMemorySaver())


@pytest.fixture(autouse=True)
def isolate_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(run_failures, "DATABASE", tmp_path / "failures.sqlite3")
    monkeypatch.setattr(chat_execution.Collector, "start", AsyncMock())
    monkeypatch.setattr(chat_execution.Collector, "report", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_execution.SubagentRecorder, "save", AsyncMock())
    monkeypatch.setattr(chat_execution, "take_pending", lambda thread_id: [])


def event(kind, *, name="model", run_id="model-1", parents=(), **data):
    return {
        "event": kind,
        "name": name,
        "run_id": run_id,
        "parent_ids": list(parents),
        "data": data,
        "tags": [],
        "metadata": {},
    }


def execute(agent, user_input="你好", user_text="你好"):
    return chat_execution.stream_agent_events(
        agent=agent,
        user_input=user_input,
        user_text=user_text,
        thread_id=THREAD_ID,
        include_tool_events=True,
        context=CONTEXT,
    )


async def test_real_graph_stream_preserves_protocol_and_artifact_order(agent, monkeypatch):
    artifact = Artifact("a" * 32, "report.pdf", 12, "application/pdf", "/files/report.pdf")
    monkeypatch.setattr(chat_execution, "take_pending", lambda thread_id: [artifact])

    result = [item async for item in execute(agent)]

    assert result[0] == {"type": "message.start", "thread_id": THREAD_ID}
    assert "".join(item["delta"] for item in result if item["type"] == "message.delta") == "结果"
    assert "".join(item["delta"] for item in result if item["type"] == "reasoning.delta") == "思考"
    types = [item["type"] for item in result]
    assert types.count("assistant.start") == 1
    assert types.index("artifact.created") < types.index("message.end")
    assert result[-1] == {
        "type": "message.end",
        "thread_id": THREAD_ID,
        "usage": {"total_chars": 2, "reasoning_chars": 2},
    }
    assert {
        "type": "human.pending",
        "thread_id": THREAD_ID,
        "approvals": [],
        "questions": [],
    } in result
    assert "done" not in types


async def test_failure_saves_latest_partial_before_emitting_error(agent, monkeypatch):
    async def fail(*args, **kwargs):
        yield event("on_chat_model_start", input={})
        yield event("on_chat_model_stream", chunk=AIMessageChunk(content="上一段", id="previous"))
        yield event("on_chat_model_end", output=AIMessage(content="上一段", id="previous"))
        yield event("on_chat_model_start", run_id="model-2", input={})
        yield event(
            "on_chat_model_stream",
            run_id="model-2",
            chunk=AIMessageChunk(content="<think>思考</think>未完成<thi", id="partial"),
        )
        raise RuntimeError("model transport failed")

    monkeypatch.setattr(chat_execution, "stream_once", fail)
    result = []
    async for item in execute(agent, user_input="你好\n[附件提取的文档全文]", user_text="你好"):
        result.append(item)
        if item["type"] == "error":
            failure = run_failures.load_failures(THREAD_ID)[0]
            assert failure["content"] == "未完成<thi"
            assert failure["reasoning"] == "思考"
            assert failure["failure"]["stage"] == "model"
            assert failure["failure"]["input"] == "你好"

    assert result[-1]["type"] == "error"
    assert not any(item["type"] in {"done", "message.end"} for item in result)
    assert (
        "".join(item["delta"] for item in result if item["type"] == "message.delta")
        == "上一段未完成<thi"
    )


async def test_cancellation_persists_partial_and_propagates(agent, monkeypatch):
    async def cancelled(*args, **kwargs):
        yield event("on_chat_model_start", input={})
        yield event("on_chat_model_stream", chunk=AIMessageChunk(content="保留<thi", id="partial"))
        raise asyncio.CancelledError

    monkeypatch.setattr(chat_execution, "stream_once", cancelled)
    result = []
    with pytest.raises(asyncio.CancelledError):
        async for item in execute(agent):
            result.append(item)

    failure = run_failures.load_failures(THREAD_ID)[0]
    assert failure["content"] == "保留<thi"
    assert failure["failure"]["error_type"] == "CancelledError"
    assert result[-1]["type"] == "error"
    assert not any(item["type"] == "done" for item in result)


async def test_tool_failure_keeps_artifacts_metrics_and_failure_location(agent, monkeypatch):
    async def fail(*args, **kwargs):
        yield event("on_chat_model_start", input={})
        yield event("on_chat_model_stream", chunk=AIMessageChunk(content="已开始生成"))
        yield event("on_chat_model_end", output=AIMessage(content="已开始生成"))
        yield event("on_tool_start", name="write_file", run_id="tool-1", input={})
        yield event("on_tool_error", name="write_file", run_id="tool-1", error=OSError())
        raise OSError("write failed")

    statistics = {"type": "metrics", "thread_id": THREAD_ID, "metrics": {"tool_calls": 1}}

    async def report(self, finish=False):
        return statistics if finish else None

    artifact = Artifact("a" * 32, "report.pdf", 12, "application/pdf", "/files/report.pdf")
    monkeypatch.setattr(chat_execution, "stream_once", fail)
    monkeypatch.setattr(chat_execution, "take_pending", lambda thread_id: [artifact])
    monkeypatch.setattr(chat_execution.Collector, "report", report)

    result = [item async for item in execute(agent)]

    assert result[-3]["type"] == "artifact.created"
    assert result[-3]["artifact"] == artifact.to_dict()
    assert result[-2] == statistics
    assert result[-1]["type"] == "error"
    failure = run_failures.load_failures(THREAD_ID)[0]["failure"]
    assert failure["stage"] == "tool"
    assert failure["tool_name"] == "write_file"


@pytest.mark.parametrize("user_input", [None, Command(resume={"answer": "继续"})])
async def test_resume_input_and_context_are_forwarded_unchanged(agent, monkeypatch, user_input):
    observed = []

    async def stream(received_agent, received_input, *, thread_id, context):
        observed.append((received_agent, received_input, thread_id, context))
        if False:
            yield

    monkeypatch.setattr(chat_execution, "stream_once", stream)
    result = [item async for item in execute(agent, user_input, user_text="")]

    assert observed == [(agent, user_input, THREAD_ID, CONTEXT)]
    assert result[-1]["type"] == "message.end"


async def test_pending_interaction_marks_unfinished_subagent_waiting(agent, monkeypatch):
    pending = {"approvals": [{"id": "approval-1"}], "questions": []}
    finish = AsyncMock()
    monkeypatch.setattr(chat_execution, "pending", AsyncMock(return_value=pending))
    monkeypatch.setattr(chat_execution.SubagentRecorder, "finish", finish)

    result = [item async for item in execute(agent)]

    finish.assert_awaited_once_with("waiting")
    assert {"type": "human.pending", "thread_id": THREAD_ID, **pending} in result


def test_tool_failures_and_custom_events_keep_the_public_protocol():
    state = StreamState(THREAD_ID, include_tool_events=True)
    state.convert(event("on_tool_start", name="run_python", run_id="tool-1", input={}))
    result = state.convert(
        event(
            "on_tool_end",
            name="run_python",
            run_id="tool-1",
            output=ToolMessage(content="execution failed", status="error", tool_call_id="call-1"),
        )
    )
    assert result == [
        {
            "type": "tool.end",
            "thread_id": THREAD_ID,
            "name": "run_python",
            "call_id": "tool-1",
            "ok": False,
            "result": "execution failed",
        }
    ]

    state.convert(event("on_tool_start", name="read_file", run_id="tool-2", input={}))
    result = state.convert(
        event("on_tool_error", name="read_file", run_id="tool-2", error=OSError())
    )
    assert result[0]["ok"] is False
    assert state.stage == "tool"
    assert state.failed_tool == "read_file"

    approval = {"thread_id": THREAD_ID, "id": "approval-1"}
    assert state.convert(event("on_custom_event", name="approval.updated", **approval)) == [
        {"type": "approval.updated", "thread_id": THREAD_ID, "approval": approval}
    ]
    assert state.convert(event("on_custom_event", name="approval.updated", thread_id="other")) == []
    assert state.convert(
        event("on_custom_event", name="investment.progress", stage="search", message="查询中")
    ) == [
        {
            "type": "research.progress",
            "thread_id": THREAD_ID,
            "stage": "search",
            "message": "查询中",
        }
    ]
