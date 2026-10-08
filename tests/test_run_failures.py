"""取消来源随真实后台任务传递，执行边界只持久化一次失败。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest

from api import chat_execution, run_failures, stream_runs
from core.context_type import MemoryContext

THREAD = "alice-12345678"


@pytest.fixture
def persistence(monkeypatch, tmp_path):
    monkeypatch.setattr(run_failures, "DATABASE", tmp_path / "failures.sqlite3")
    lease = SimpleNamespace(execute=AsyncMock(), close=AsyncMock())
    finish = AsyncMock()
    monkeypatch.setattr(stream_runs.run_store, "claim", AsyncMock(return_value=lease))
    monkeypatch.setattr(stream_runs.run_store, "finish", finish)
    failure = AsyncMock(wraps=run_failures.capture_failure)
    monkeypatch.setattr(stream_runs, "capture_failure", failure)
    monkeypatch.setattr(chat_execution, "capture_failure", failure)
    monkeypatch.setattr(chat_execution.Collector, "start", AsyncMock())
    monkeypatch.setattr(chat_execution.Collector, "report", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_execution, "take_pending", lambda thread_id: [])
    agent = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values={"messages": []}))
    )
    return SimpleNamespace(lease=lease, finish=finish, failure=failure, agent=agent)


@pytest.mark.parametrize("execution_boundary", [False, True])
@pytest.mark.parametrize(
    ("reason", "message", "status"),
    [
        ("user_stop", "已停止", "stopped"),
        ("server_shutdown", "服务已关闭，任务执行中断", "interrupted"),
        ("lease_lost", "会话执行锁连接丢失，任务执行中断", "interrupted"),
    ],
)
async def test_background_cancellation_records_one_accurate_failure(
    persistence, monkeypatch, execution_boundary, reason, message, status
):
    generating = asyncio.Event()
    check_lease = asyncio.Event()

    async def wait_for_lease_check(seconds):
        await check_lease.wait()

    async def waiting(*args, **kwargs):
        generating.set()
        await asyncio.Event().wait()
        if False:
            yield

    monkeypatch.setattr(stream_runs.asyncio, "sleep", wait_for_lease_check)
    events = waiting()
    if execution_boundary:
        monkeypatch.setattr(chat_execution, "stream_once", waiting)
        events = chat_execution.stream_agent_events(
            agent=persistence.agent,
            user_input="test",
            user_text="test",
            thread_id=THREAD,
            include_tool_events=True,
            context=MemoryContext(user_id="alice"),
        )
    lock = asyncio.Lock()
    await lock.acquire()
    run = await stream_runs.start_run(
        THREAD,
        base_count=0,
        user_input="test",
        events=events,
        lock=lock,
        agent=persistence.agent,
    )
    await generating.wait()

    if reason == "server_shutdown":
        await stream_runs.shutdown_runs()
    elif reason == "lease_lost":
        persistence.lease.execute.side_effect = psycopg.OperationalError("connection closed")
        check_lease.set()
    else:
        run_failures.request_user_stop(run.task)
    with pytest.raises(asyncio.CancelledError):
        await run.task

    records = run_failures.load_failures(THREAD)
    assert len(records) == 1
    failure = records[0]["failure"]
    assert failure["reason"] == reason
    assert failure["message"] == message
    assert failure["error_type"] == "CancelledError"
    replay = [event async for event in run.follow()]
    assert [event["failure"] for event in replay if event["type"] == "error"] == [failure]
    assert sum(event["type"] == "done" for event in replay) == 1
    persistence.failure.assert_awaited_once()
    persistence.finish.assert_awaited_once_with(persistence.lease, THREAD, status)
    assert not lock.locked()
    assert stream_runs.active_run(THREAD) is None


@pytest.mark.parametrize(
    ("first_reason", "later_reason"),
    [
        ("user_stop", "server_shutdown"),
        ("server_shutdown", "lease_lost"),
        ("lease_lost", "user_stop"),
    ],
)
async def test_later_cancellation_does_not_replace_the_first_reason(
    persistence, first_reason, later_reason
):
    running = asyncio.Event()
    cancelled = asyncio.Event()
    finish_cleanup = asyncio.Event()

    async def execute():
        running.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            cancelled.set()
            await finish_cleanup.wait()
            await run_failures.capture_failure(persistence.agent, THREAD, exc)
            raise

    task = asyncio.create_task(execute())
    await running.wait()
    run_failures.request_cancellation(task, first_reason)
    await cancelled.wait()
    run_failures.request_cancellation(task, later_reason)
    assert task.cancelling() == 1
    finish_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    records = run_failures.load_failures(THREAD)
    assert len(records) == 1
    assert records[0]["failure"]["reason"] == first_reason
