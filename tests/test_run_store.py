"""持久化运行开始前的租约排他性和失败释放。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
from fastapi import HTTPException

from api import run_store

THREAD = "alice-12345678"


@pytest.mark.parametrize("acquired", [False, True])
async def test_acquire_only_locks_without_replacing_previous_run(monkeypatch, acquired):
    cursor = SimpleNamespace(fetchone=AsyncMock(return_value={"acquired": acquired}))
    lease = SimpleNamespace(execute=AsyncMock(return_value=cursor), close=AsyncMock())
    monkeypatch.setattr(run_store, "connect", AsyncMock(return_value=lease))

    if acquired:
        assert await run_store.acquire(THREAD) is lease
        lease.close.assert_not_called()
    else:
        with pytest.raises(HTTPException) as error:
            await run_store.acquire(THREAD)
        assert error.value.status_code == 409
        lease.close.assert_awaited_once()
    assert lease.execute.await_count == 1
    assert lease.execute.await_args.args[0].startswith("SELECT pg_try_advisory_lock")


async def test_begin_failure_releases_claimed_connection_and_preserves_error(monkeypatch):
    lease = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(run_store, "acquire", AsyncMock(return_value=lease))
    monkeypatch.setattr(
        run_store, "begin", AsyncMock(side_effect=psycopg.OperationalError("database unavailable"))
    )

    with pytest.raises(psycopg.OperationalError, match="database unavailable"):
        await run_store.claim(THREAD)

    lease.close.assert_awaited_once()


async def test_claim_cancellation_waits_for_connection_close(monkeypatch):
    beginning = asyncio.Event()
    closing = asyncio.Event()
    complete_close = asyncio.Event()

    async def begin(*args):
        beginning.set()
        await asyncio.Event().wait()

    async def close():
        closing.set()
        await complete_close.wait()

    lease = SimpleNamespace(close=AsyncMock(side_effect=close))
    monkeypatch.setattr(run_store, "acquire", AsyncMock(return_value=lease))
    monkeypatch.setattr(run_store, "begin", begin)
    claim = asyncio.create_task(run_store.claim(THREAD))
    await beginning.wait()
    claim.cancel()
    await closing.wait()
    claim.cancel()
    complete_close.set()
    with pytest.raises(asyncio.CancelledError):
        await claim

    lease.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("finished_status", "expected_status"),
    [
        ("completed", "completed"),
        ("stopped", "stopped"),
        ("waiting", "waiting"),
        ("running", "interrupted"),
    ],
)
async def test_status_rechecks_state_after_the_previous_owner_releases_its_lease(
    monkeypatch, finished_status, expected_status
):
    stored = {"status": "running"}
    checking_lock = asyncio.Event()
    owner_finished = asyncio.Event()

    async def execute(query, parameters):
        if query.startswith("SELECT status"):
            result = stored.copy()
        elif query.startswith("SELECT pg_try_advisory_lock"):
            checking_lock.set()
            await owner_finished.wait()
            result = {"acquired": True}
        else:
            stored["status"] = "interrupted"
            result = None
        return SimpleNamespace(fetchone=AsyncMock(return_value=result))

    connection = AsyncMock()
    connection.__aenter__.return_value = connection
    connection.execute.side_effect = execute
    monkeypatch.setattr(run_store, "connect", AsyncMock(return_value=connection))
    reading = asyncio.create_task(run_store.status(THREAD))
    await checking_lock.wait()
    # 第一次 SELECT 已读到 running，持锁生产者随后才提交终态并释放连接。
    stored["status"] = finished_status
    owner_finished.set()

    assert await reading == expected_status
    assert stored["status"] == expected_status
