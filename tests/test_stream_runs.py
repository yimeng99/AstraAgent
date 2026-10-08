"""后台运行的所有权、终态、取消与独立订阅契约。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest

from api import stream_runs

THREAD = "alice-12345678"


@pytest.fixture
def backend(monkeypatch):
    lease = SimpleNamespace(execute=AsyncMock(), close=AsyncMock())
    claim = AsyncMock(return_value=lease)
    begin = AsyncMock()
    finish = AsyncMock()

    async def record(agent, thread_id, error, **kwargs):
        return {
            "type": "error",
            "thread_id": thread_id,
            "error": "任务执行中断",
            "failure": {"reason": "execution_error", "error_type": type(error).__name__},
        }

    failure = AsyncMock(side_effect=record)
    monkeypatch.setattr(stream_runs.run_store, "claim", claim)
    monkeypatch.setattr(stream_runs.run_store, "begin", begin)
    monkeypatch.setattr(stream_runs.run_store, "finish", finish)
    monkeypatch.setattr(stream_runs, "capture_failure", failure)
    return SimpleNamespace(lease=lease, claim=claim, begin=begin, finish=finish, failure=failure)


async def start(events, *, thread_id=THREAD):
    lock = asyncio.Lock()
    await lock.acquire()
    run = await stream_runs.start_run(
        thread_id, base_count=0, user_input="test", events=events, lock=lock, agent=object()
    )
    return run, lock


async def stream(*events):
    for event in events:
        yield event


async def replay(run):
    return [event async for event in run.follow()]


@pytest.mark.parametrize(
    ("events", "status"),
    [
        ([{"type": "message.delta", "delta": "hello"}], "completed"),
        ([{"type": "human.pending", "approvals": [{"id": "a"}], "questions": []}], "waiting"),
        ([{"type": "human.pending", "approvals": [], "questions": []}], "completed"),
    ],
)
async def test_finished_stream_has_one_done_after_persistence(backend, events, status):
    persisted = asyncio.Event()
    release_finish = asyncio.Event()

    async def finish(*args):
        persisted.set()
        await release_finish.wait()

    backend.finish.side_effect = finish
    run, lock = await start(stream(*events))
    await persisted.wait()
    assert not run.finished
    assert all(event["type"] != "done" for event, _ in run.events)
    release_finish.set()
    await run.task

    assert await replay(run) == [*events, {"type": "done", "thread_id": THREAD}]
    backend.finish.assert_awaited_once_with(backend.lease, THREAD, status)
    assert not lock.locked()
    assert stream_runs.active_run(THREAD) is None


async def test_exception_overrides_earlier_pending_state(backend):
    async def broken():
        yield {"type": "human.pending", "approvals": [], "questions": []}
        raise RuntimeError("failed after pending")

    run, lock = await start(broken())
    await run.task

    assert [event["type"] for event in await replay(run)] == ["human.pending", "error", "done"]
    backend.finish.assert_awaited_once_with(backend.lease, THREAD, "failed")
    backend.failure.assert_awaited_once()
    assert not lock.locked()


@pytest.mark.parametrize(
    ("reason", "error_type", "status"),
    [
        ("user_stop", "CancelledError", "stopped"),
        ("execution_error", "CancelledError", "interrupted"),
    ],
)
async def test_recorded_cancellation_is_not_saved_twice(backend, reason, error_type, status):
    async def cancelled():
        yield {"type": "error", "failure": {"reason": reason, "error_type": error_type}}
        raise asyncio.CancelledError

    run, lock = await start(cancelled())
    with pytest.raises(asyncio.CancelledError):
        await run.task

    assert [event["type"] for event in await replay(run)] == ["error", "done"]
    backend.finish.assert_awaited_once_with(backend.lease, THREAD, status)
    backend.failure.assert_not_called()
    assert not lock.locked()


async def test_closing_subscriber_does_not_cancel_producer(backend):
    continue_generation = asyncio.Event()

    async def response():
        yield {"type": "message.delta", "delta": "first"}
        await continue_generation.wait()
        yield {"type": "message.delta", "delta": "second"}

    run, lock = await start(response())
    subscriber = run.follow()
    assert (await anext(subscriber))["delta"] == "first"
    await subscriber.aclose()
    assert not run.task.done()
    continue_generation.set()
    await run.task

    assert [event.get("delta") for event in await replay(run)] == ["first", "second", None]
    assert not lock.locked()


async def test_replay_retains_recent_events_and_signals_truncation():
    run = stream_runs.StreamRun(THREAD, 0, "test", replay_limit_bytes=140)
    for index in range(5):
        await run.publish({"type": "message.delta", "delta": str(index) * 40})
    run.finished = True

    result = await replay(run)
    assert result[0] == {"type": "stream.truncated", "thread_id": THREAD}
    assert result[-1] == {"type": "message.delta", "delta": "4" * 40}
    assert run.replay_bytes <= run.replay_limit_bytes


async def test_pending_claim_reserves_capacity(backend, monkeypatch):
    monkeypatch.setattr(stream_runs, "MAX_ACTIVE_RUNS", 1)
    claiming = asyncio.Event()
    release_claim = asyncio.Event()

    async def claim(thread_id):
        claiming.set()
        await release_claim.wait()
        return backend.lease

    backend.claim.side_effect = claim
    first = asyncio.create_task(start(stream()))
    await claiming.wait()
    rejected_lock = asyncio.Lock()
    await rejected_lock.acquire()
    with pytest.raises(stream_runs.TooManyStreamRunsError):
        await stream_runs.start_run(
            "bob-12345678",
            base_count=0,
            user_input="test",
            events=stream(),
            lock=rejected_lock,
            agent=object(),
        )
    assert not rejected_lock.locked()
    backend.claim.assert_awaited_once()
    release_claim.set()
    run, lock = await first
    await run.task
    assert not lock.locked()


async def test_failed_claim_releases_capacity_and_lock(backend):
    backend.claim.side_effect = psycopg.OperationalError("connection unavailable")
    lock = asyncio.Lock()
    await lock.acquire()
    with pytest.raises(psycopg.OperationalError):
        await stream_runs.start_run(
            THREAD, base_count=0, user_input="test", events=stream(), lock=lock, agent=object()
        )
    assert not lock.locked()
    assert THREAD not in stream_runs._starting
    assert stream_runs.active_run(THREAD) is None
    backend.finish.assert_not_called()


async def test_cancel_during_claim_releases_capacity_and_lock(backend):
    claiming = asyncio.Event()

    async def claim(thread_id):
        claiming.set()
        await asyncio.Event().wait()

    backend.claim.side_effect = claim
    lock = asyncio.Lock()
    await lock.acquire()
    starter = asyncio.create_task(
        stream_runs.start_run(
            THREAD, base_count=0, user_input="test", events=stream(), lock=lock, agent=object()
        )
    )
    await claiming.wait()
    starter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starter
    assert not lock.locked()
    assert THREAD not in stream_runs._starting
    backend.finish.assert_not_called()


async def test_cancel_during_producer_start_waits_for_cleanup(backend, monkeypatch):
    scheduled = asyncio.Event()
    begin = asyncio.Event()
    produce = stream_runs._produce

    async def delayed_produce(*args):
        scheduled.set()
        await begin.wait()
        await produce(*args)

    async def waiting():
        await asyncio.Event().wait()
        yield {"type": "message.delta", "delta": "unreachable"}

    monkeypatch.setattr(stream_runs, "_produce", delayed_produce)
    lock = asyncio.Lock()
    await lock.acquire()
    starter = asyncio.create_task(
        stream_runs.start_run(
            THREAD, base_count=0, user_input="test", events=waiting(), lock=lock, agent=object()
        )
    )
    await scheduled.wait()
    starter.cancel()
    await asyncio.sleep(0)
    starter.cancel()
    await asyncio.sleep(0)
    assert not starter.done()
    begin.set()
    with pytest.raises(asyncio.CancelledError):
        await starter

    backend.finish.assert_awaited_once_with(backend.lease, THREAD, "interrupted")
    assert not lock.locked()
    assert stream_runs.active_run(THREAD) is None


async def test_returned_task_can_be_cancelled_immediately(backend):
    async def waiting():
        await asyncio.Event().wait()
        yield {"type": "message.delta", "delta": "unreachable"}

    run, lock = await start(waiting())
    run.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run.task

    backend.finish.assert_awaited_once_with(backend.lease, THREAD, "interrupted")
    assert [event["type"] for event in await replay(run)] == ["error", "done"]
    assert not lock.locked()


async def test_database_finish_error_does_not_hold_subscription_or_lock(backend):
    backend.finish.side_effect = psycopg.OperationalError("connection lost")
    run, lock = await start(stream())
    await run.task

    assert await replay(run) == [{"type": "done", "thread_id": THREAD}]
    assert not lock.locked()
    assert stream_runs.active_run(THREAD) is None


async def test_lost_database_lease_interrupts_the_producer(backend, monkeypatch):
    backend.lease.execute.side_effect = psycopg.OperationalError("lease lost")
    monkeypatch.setattr(stream_runs.asyncio, "sleep", AsyncMock())

    async def waiting():
        await asyncio.Event().wait()
        yield {"type": "message.delta", "delta": "unreachable"}

    run, lock = await start(waiting())
    with pytest.raises(asyncio.CancelledError):
        await run.task

    backend.finish.assert_awaited_once_with(backend.lease, THREAD, "interrupted")
    assert [event["type"] for event in await replay(run)] == ["error", "done"]
    assert not lock.locked()


async def test_repeated_shutdown_does_not_interrupt_pending_persistence(backend):
    finishing = asyncio.Event()
    release_finish = asyncio.Event()

    async def finish(*args):
        finishing.set()
        await release_finish.wait()

    async def waiting():
        await asyncio.Event().wait()
        yield {"type": "message.delta", "delta": "unreachable"}

    backend.finish.side_effect = finish
    run, lock = await start(waiting())
    first_shutdown = asyncio.create_task(stream_runs.shutdown_runs())
    await finishing.wait()
    second_shutdown = asyncio.create_task(stream_runs.shutdown_runs())
    release_finish.set()
    await asyncio.gather(first_shutdown, second_shutdown)

    backend.finish.assert_awaited_once_with(backend.lease, THREAD, "interrupted")
    assert [event["type"] for event in await replay(run)] == ["error", "done"]
    assert not lock.locked()


async def test_cancel_while_stopping_watcher_still_finishes_run(backend, monkeypatch):
    closing = asyncio.Event()
    release_watcher = asyncio.Event()

    async def watcher(run, lease):
        try:
            await asyncio.Event().wait()
        finally:
            closing.set()
            await release_watcher.wait()

    async def response():
        # 让租约 watcher 先进入自己的等待，再正常结束事件流。
        await asyncio.sleep(0)
        if False:
            yield {}

    monkeypatch.setattr(stream_runs, "_watch_lease", watcher)
    run, lock = await start(response())
    await closing.wait()
    run.task.cancel()
    await asyncio.sleep(0)
    assert not run.task.done()
    release_watcher.set()
    with pytest.raises(asyncio.CancelledError):
        await run.task

    backend.finish.assert_awaited_once_with(backend.lease, THREAD, "completed")
    assert await replay(run) == [{"type": "done", "thread_id": THREAD}]
    assert not lock.locked()
    assert stream_runs.active_run(THREAD) is None


async def test_repeated_cancel_waits_for_the_same_cleanup_task(backend):
    finishing = asyncio.Event()
    release_finish = asyncio.Event()

    async def finish(*args):
        finishing.set()
        await release_finish.wait()

    backend.finish.side_effect = finish
    run, lock = await start(stream())
    await finishing.wait()
    for _ in range(2):
        run.task.cancel()
        await asyncio.sleep(0)
        assert not run.task.done()
        assert lock.locked()
        assert not run.finished
    release_finish.set()
    with pytest.raises(asyncio.CancelledError):
        await run.task

    backend.finish.assert_awaited_once_with(backend.lease, THREAD, "completed")
    assert await replay(run) == [{"type": "done", "thread_id": THREAD}]
    assert not lock.locked()
    assert stream_runs.active_run(THREAD) is None


async def test_supplied_lease_begins_after_capacity_reservation(backend):
    async def begin(lease, thread_id):
        assert thread_id in stream_runs._starting

    backend.begin.side_effect = begin
    lock = asyncio.Lock()
    await lock.acquire()
    run = await stream_runs.start_run(
        THREAD,
        base_count=0,
        user_input="test",
        events=stream(),
        lock=lock,
        agent=object(),
        lease=backend.lease,
    )
    await run.task

    backend.claim.assert_not_called()
    backend.begin.assert_awaited_once_with(backend.lease, THREAD)
    backend.finish.assert_awaited_once_with(backend.lease, THREAD, "completed")
    backend.lease.close.assert_not_called()
    assert not lock.locked()


async def test_capacity_rejection_closes_supplied_lease(backend, monkeypatch):
    monkeypatch.setattr(stream_runs, "MAX_ACTIVE_RUNS", 0)
    lock = asyncio.Lock()
    await lock.acquire()
    with pytest.raises(stream_runs.TooManyStreamRunsError):
        await stream_runs.start_run(
            THREAD,
            base_count=0,
            user_input="test",
            events=stream(),
            lock=lock,
            agent=object(),
            lease=backend.lease,
        )

    backend.claim.assert_not_called()
    backend.begin.assert_not_called()
    backend.lease.close.assert_awaited_once()
    assert not lock.locked()
    assert THREAD not in stream_runs._starting


async def test_begin_failure_closes_supplied_lease_and_releases_capacity(backend):
    backend.begin.side_effect = psycopg.OperationalError("begin failed")
    lock = asyncio.Lock()
    await lock.acquire()
    with pytest.raises(psycopg.OperationalError):
        await stream_runs.start_run(
            THREAD,
            base_count=0,
            user_input="test",
            events=stream(),
            lock=lock,
            agent=object(),
            lease=backend.lease,
        )

    backend.claim.assert_not_called()
    backend.lease.close.assert_awaited_once()
    assert not lock.locked()
    assert THREAD not in stream_runs._starting


async def test_cancel_during_begin_closes_supplied_lease(backend):
    beginning = asyncio.Event()

    async def begin(lease, thread_id):
        beginning.set()
        await asyncio.Event().wait()

    backend.begin.side_effect = begin
    lock = asyncio.Lock()
    await lock.acquire()
    starter = asyncio.create_task(
        stream_runs.start_run(
            THREAD,
            base_count=0,
            user_input="test",
            events=stream(),
            lock=lock,
            agent=object(),
            lease=backend.lease,
        )
    )
    await beginning.wait()
    starter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starter

    backend.lease.close.assert_awaited_once()
    assert not lock.locked()
    assert THREAD not in stream_runs._starting


async def test_repeated_cancel_cannot_interrupt_rejected_lease_close(backend, monkeypatch):
    closing = asyncio.Event()
    release_close = asyncio.Event()

    async def close():
        closing.set()
        await release_close.wait()

    backend.lease.close.side_effect = close
    monkeypatch.setattr(stream_runs, "MAX_ACTIVE_RUNS", 0)
    lock = asyncio.Lock()
    await lock.acquire()
    starter = asyncio.create_task(
        stream_runs.start_run(
            THREAD,
            base_count=0,
            user_input="test",
            events=stream(),
            lock=lock,
            agent=object(),
            lease=backend.lease,
        )
    )
    await closing.wait()
    for _ in range(2):
        starter.cancel()
        await asyncio.sleep(0)
        assert not starter.done()
        assert lock.locked()
    release_close.set()
    with pytest.raises(asyncio.CancelledError):
        await starter

    backend.lease.close.assert_awaited_once()
    assert not lock.locked()
