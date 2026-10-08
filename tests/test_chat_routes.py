"""HTTP 入口共享输入、并发拒绝和后台锁所有权的集成契约。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessage
from langgraph.types import Command

from api import run_store, stream_runs
from api.deps import current_context, get_agent, get_config
from api.routes import chat, interactions
from core.context_type import new_context

THREAD = "alice-12345678"
REQUEST = {"thread_id": THREAD, "user_input": "请分析附件"}
EMPTY_PENDING = {"approvals": [], "questions": []}


class CountedLock(asyncio.Lock):
    def __init__(self):
        super().__init__()
        self.releases = 0

    def release(self):
        self.releases += 1
        super().release()


@pytest.fixture
async def api(monkeypatch):
    app = FastAPI()
    app.include_router(chat.router)
    app.include_router(interactions.router)
    lock = CountedLock()
    context = new_context(user_id="alice")
    snapshot = SimpleNamespace(
        config={"configurable": {"thread_id": THREAD, "checkpoint_id": "checkpoint-1"}},
        next=("model",),
        tasks=(),
        values={"messages": []},
    )
    graph = SimpleNamespace(
        config={"recursion_limit": 125},
        ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="分析完成")]}),
        aget_state=AsyncMock(return_value=snapshot),
    )
    app.dependency_overrides[get_agent] = lambda: graph
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(llm=object())
    app.dependency_overrides[current_context] = lambda: context
    prepared = [{"type": "text", "text": "正文与已解析附件"}]
    build_input = AsyncMock(return_value=prepared)
    history = AsyncMock(
        return_value=[SimpleNamespace(role="user"), SimpleNamespace(role="assistant")]
    )
    pending = AsyncMock(return_value=EMPTY_PENDING)
    prepare_resume = AsyncMock(return_value=Command(resume={"approval-1": {"approve": True}}))
    prepare_batch = AsyncMock(return_value=prepare_resume.return_value)
    lease = SimpleNamespace(execute=AsyncMock(), close=AsyncMock())
    acquire = AsyncMock(return_value=lease)
    begin = AsyncMock()
    claim = AsyncMock(return_value=lease)
    finish = AsyncMock()
    executions = []

    async def execute(**kwargs):
        assert lock.locked()
        executions.append(kwargs)
        yield {"type": "message.delta", "thread_id": THREAD, "delta": "分析完成"}
        yield {"type": "human.pending", "thread_id": THREAD, **EMPTY_PENDING}

    monkeypatch.setattr(chat, "supports_vision", lambda llm: True)
    monkeypatch.setattr(chat, "build_user_content", build_input)
    monkeypatch.setattr(chat, "thread_lock", lambda thread_id: lock)
    monkeypatch.setattr(interactions, "thread_lock", lambda thread_id: lock)
    monkeypatch.setattr(chat, "load_thread_messages", history)
    monkeypatch.setattr(interactions, "load_thread_messages", history)
    monkeypatch.setattr(chat, "pending", pending)
    monkeypatch.setattr(interactions, "pending", pending)
    monkeypatch.setattr(chat, "stream_agent_events", execute)
    monkeypatch.setattr(interactions, "stream_agent_events", execute)
    monkeypatch.setattr(interactions, "prepare_resume", prepare_resume)
    monkeypatch.setattr(interactions, "prepare_approval_batch", prepare_batch)
    monkeypatch.setattr(run_store, "acquire", acquire)
    monkeypatch.setattr(run_store, "begin", begin)
    monkeypatch.setattr(run_store, "claim", claim)
    monkeypatch.setattr(run_store, "finish", finish)
    monkeypatch.setattr(run_store, "status", AsyncMock(return_value="interrupted"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client,
            lock=lock,
            graph=graph,
            prepared=prepared,
            build_input=build_input,
            pending=pending,
            history=history,
            prepare_resume=prepare_resume,
            prepare_batch=prepare_batch,
            lease=lease,
            acquire=acquire,
            begin=begin,
            claim=claim,
            finish=finish,
            executions=executions,
        )


def sse_events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


async def test_sync_and_stream_share_attachment_input_and_preserve_user_text(api):
    attachment = {"file_id": "a" * 32, "filename": "报告.pdf"}
    request = {**REQUEST, "attachments": [attachment]}
    sync_response = await api.client.post("/chat", json=request)
    stream_response = await api.client.post("/chat/stream", json=request)

    assert sync_response.status_code == stream_response.status_code == 200
    assert sync_response.json()["data"]["reply"] == "分析完成"
    assert api.graph.ainvoke.await_args.args[0] == {
        "messages": [{"role": "user", "content": api.prepared}]
    }
    execution = api.executions[0]
    assert execution["user_input"] == api.prepared
    assert execution["user_text"] == REQUEST["user_input"]
    assert execution["context"].extra["approval_thread_id"] == THREAD
    assert api.build_input.await_count == 2
    for call in api.build_input.await_args_list:
        assert call.args[0] == REQUEST["user_input"]
        assert call.args[1][0].file_id == attachment["file_id"]
        assert call.kwargs["vision"] is True
    assert [event["type"] for event in sse_events(stream_response)].count("done") == 1
    assert api.lock.releases == 2
    assert not api.lock.locked()


@pytest.mark.parametrize("first_path", ["/chat", "/chat/stream"])
async def test_busy_conversation_rejects_both_entrypoints_before_preparing_input(
    api, monkeypatch, first_path
):
    entered = asyncio.Event()
    complete = asyncio.Event()

    async def invoke(*args, **kwargs):
        entered.set()
        await complete.wait()
        return {"messages": [AIMessage(content="完成")]}

    async def execute(**kwargs):
        entered.set()
        await complete.wait()
        yield {"type": "message.delta", "thread_id": THREAD, "delta": "完成"}

    api.graph.ainvoke.side_effect = invoke
    monkeypatch.setattr(chat, "stream_agent_events", execute)
    first_request = asyncio.create_task(api.client.post(first_path, json=REQUEST))
    await entered.wait()
    try:
        for path in ("/chat", "/chat/stream"):
            rejected = await api.client.post(path, json=REQUEST)
            assert rejected.status_code == 409
        assert api.build_input.await_count == 1
    finally:
        complete.set()
        response = await first_request

    assert response.status_code == 200
    assert api.lock.releases == 1
    assert not api.lock.locked()


@pytest.mark.parametrize("failure", ["capacity", "claim"])
@pytest.mark.parametrize("route", ["chat", "resume", "recover"])
async def test_start_failure_preserves_original_error_and_releases_lock_once(
    api, monkeypatch, failure, route
):
    if failure == "capacity":
        monkeypatch.setattr(stream_runs, "MAX_ACTIVE_RUNS", 0)
        expected_status = 503
    else:
        api.claim.side_effect = HTTPException(409, "会话已被其他进程占用")
        api.acquire.side_effect = api.claim.side_effect
        expected_status = 409
    path, body = {
        "chat": ("/chat/stream", REQUEST),
        "resume": (f"/threads/{THREAD}/resume", {"id": "approval-1", "approve": True}),
        "recover": (f"/threads/{THREAD}/recover", {"checkpoint_id": "checkpoint-1"}),
    }[route]

    response = await api.client.post(path, json=body)

    assert response.status_code == expected_status
    if failure == "claim":
        assert response.json()["detail"] == "会话已被其他进程占用"
    assert api.lock.releases == 1
    assert not api.lock.locked()
    assert api.executions == []
    api.finish.assert_not_called()
    api.begin.assert_not_called()


@pytest.mark.parametrize("continues", [False, True])
async def test_resume_hands_off_lock_and_has_one_terminal_event(api, continues):
    api.pending.return_value = {
        "approvals": [{"id": "approval-1:write"}, {"id": "approval-2:write"}],
        "questions": [],
    }
    if not continues:
        api.prepare_resume.return_value = None

    response = await api.client.post(
        f"/threads/{THREAD}/resume", json={"id": "approval-1:write", "approve": True}
    )

    assert response.status_code == 200
    events = sse_events(response)
    assert events[-1] == {"type": "done", "thread_id": THREAD}
    assert sum(event["type"] == "done" for event in events) == 1
    assert events[0]["type"] == "human.pending"
    if continues:
        assert events[0]["approvals"] == [{"id": "approval-2:write"}]
        assert api.executions[0]["user_input"] is api.prepare_resume.return_value
        assert api.executions[0]["user_text"] == ""
        expected_status = "completed"
    else:
        assert events[0]["approvals"] == api.pending.return_value["approvals"]
        assert api.executions == []
        expected_status = "waiting"
    api.finish.assert_awaited_once_with(api.claim.return_value, THREAD, expected_status)
    assert api.lock.releases == 1
    assert not api.lock.locked()


async def test_recover_hands_off_checkpoint_without_new_user_message_or_duplicate_done(api):
    response = await api.client.post(
        f"/threads/{THREAD}/recover", json={"checkpoint_id": "checkpoint-1"}
    )

    assert response.status_code == 200
    events = sse_events(response)
    assert [event["type"] for event in events] == ["message.delta", "human.pending", "done"]
    assert api.executions[0]["user_input"] is None
    assert api.executions[0]["user_text"] == ""
    assert api.graph.aget_state.await_count == 1
    api.finish.assert_awaited_once_with(api.claim.return_value, THREAD, "completed")
    assert api.lock.releases == 1
    assert not api.lock.locked()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/chat", REQUEST),
        ("/chat/stream", REQUEST),
        (f"/threads/{THREAD}/resume", {"id": "approval-1", "approve": True}),
        (f"/threads/{THREAD}/resume", {"ids": ["approval-1"], "approve": True}),
        (f"/threads/{THREAD}/recover", {"checkpoint_id": "checkpoint-1"}),
    ],
)
async def test_other_process_rejects_before_attachment_or_approval_work(api, path, body):
    api.claim.side_effect = HTTPException(409, "会话已被其他进程占用")
    api.acquire.side_effect = api.claim.side_effect

    response = await api.client.post(path, json=body)

    assert response.status_code == 409
    api.build_input.assert_not_called()
    api.history.assert_not_called()
    api.graph.ainvoke.assert_not_called()
    api.graph.aget_state.assert_not_called()
    api.prepare_resume.assert_not_called()
    api.prepare_batch.assert_not_called()
    api.begin.assert_not_called()
    api.finish.assert_not_called()
    assert api.lock.releases == 1
    assert not api.lock.locked()


@pytest.mark.parametrize("route", ["resume", "recover"])
async def test_rejected_preparation_closes_lease_without_changing_run_status(api, route):
    if route == "resume":
        api.prepare_resume.side_effect = HTTPException(422, "请填写回答")
        body = {"id": "question-1", "answer": " "}
        expected_status = 422
    else:
        body = {"checkpoint_id": "outdated-checkpoint"}
        expected_status = 409

    response = await api.client.post(f"/threads/{THREAD}/{route}", json=body)

    assert response.status_code == expected_status
    api.acquire.assert_awaited_once_with(THREAD)
    api.lease.close.assert_awaited_once()
    api.begin.assert_not_called()
    api.finish.assert_not_called()
    assert api.lock.releases == 1
    assert not api.lock.locked()


async def test_sync_waiting_status_is_persisted_before_return(api):
    api.pending.return_value = {"approvals": [{"id": "approval-1"}], "questions": []}

    response = await api.client.post("/chat", json=REQUEST)

    assert response.status_code == 200
    api.claim.assert_awaited_once_with(THREAD)
    api.finish.assert_awaited_once_with(api.lease, THREAD, "waiting")
    assert not api.lock.locked()


async def test_sync_failure_persists_failed_without_replacing_original_exception(api):
    api.graph.ainvoke.side_effect = RuntimeError("model unavailable")

    with pytest.raises(RuntimeError, match="model unavailable"):
        await api.client.post("/chat", json=REQUEST)

    api.finish.assert_awaited_once_with(api.lease, THREAD, "failed")
    assert api.lock.releases == 1
    assert not api.lock.locked()


async def test_repeated_sync_cancellation_waits_for_persistence_before_releasing_lock(api):
    generating = asyncio.Event()
    finishing = asyncio.Event()
    complete_finish = asyncio.Event()

    async def invoke(*args, **kwargs):
        generating.set()
        await asyncio.Event().wait()

    async def finish(*args):
        finishing.set()
        await complete_finish.wait()

    api.graph.ainvoke.side_effect = invoke
    api.finish.side_effect = finish
    request = asyncio.create_task(api.client.post("/chat", json=REQUEST))
    await generating.wait()
    request.cancel()
    await finishing.wait()
    request.cancel()
    assert api.lock.locked()
    complete_finish.set()
    with pytest.raises(asyncio.CancelledError):
        await request

    api.finish.assert_awaited_once_with(api.lease, THREAD, "interrupted")
    assert api.lock.releases == 1
    assert not api.lock.locked()
