"""持久化运行状态；PG 会话锁保证只有一个进程执行同一会话。"""

import asyncio
import hashlib
import os
from typing import Any, cast
from uuid import uuid4

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from api.task_cleanup import wait_for_cleanup

type RunConnection = psycopg.AsyncConnection[dict[str, Any]]


async def connect() -> RunConnection:
    """创建持有会话租约的独立 PG 连接。"""
    url = os.getenv("POSTGRES_URL", "")
    if not url:
        raise HTTPException(503, "任务持久化需要配置 POSTGRES_URL")
    return await psycopg.AsyncConnection.connect(
        url, autocommit=True, row_factory=dict_row, connect_timeout=5
    )


def lock_key(thread_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(("agent-run:" + thread_id).encode()).digest()[:8], "big", signed=True
    )


async def setup() -> None:
    """创建任务及其展示记录需要的表。"""
    async with await connect() as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS agent_runs (
            thread_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            status TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    from api.metrics import setup as setup_metrics

    await setup_metrics()
    from api.subagent_runs import setup as setup_subagents

    await setup_subagents()


async def acquire(thread_id: str) -> RunConnection:
    """只取得跨进程会话锁；请求准备失败不会改写上一次运行状态。"""
    db = await connect()
    try:
        row = await (
            await db.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (lock_key(thread_id),))
        ).fetchone()
        assert row is not None  # SELECT 表达式总是返回一行。
        if not row["acquired"]:
            raise HTTPException(409, "当前会话正在其他任务中执行")
        return db
    except BaseException:
        await wait_for_cleanup(asyncio.create_task(db.close()))
        raise


async def begin(db: RunConnection, thread_id: str) -> None:
    """持有会话锁的调用方已准备好输入，现在才建立本次运行记录。"""
    await db.execute(
        """INSERT INTO agent_runs(thread_id,run_id,status) VALUES(%s,%s,'running')
        ON CONFLICT(thread_id) DO UPDATE SET run_id=excluded.run_id,status='running',updated_at=now()""",
        (thread_id, str(uuid4())),
    )


async def claim(thread_id: str) -> RunConnection:
    """取得会话锁并立即开始一次运行，调用方负责 finish。"""
    db = await acquire(thread_id)
    try:
        await begin(db, thread_id)
        return db
    except BaseException:
        await wait_for_cleanup(asyncio.create_task(db.close()))
        raise


async def finish(db: RunConnection, thread_id: str, status: str) -> None:
    """保存终态并释放租约；调用方须等待整个收尾完成。"""
    try:
        await db.execute(
            "UPDATE agent_runs SET status=%s,updated_at=now() WHERE thread_id=%s",
            (status, thread_id),
        )
    finally:
        await db.close()


async def status(thread_id: str) -> str:
    """读取持久化状态，只有确认没有持锁者时才修正为 interrupted。"""
    async with await connect() as db:
        row = await (
            await db.execute("SELECT status FROM agent_runs WHERE thread_id=%s", (thread_id,))
        ).fetchone()
        if not row:
            return "unknown"
        if row["status"] != "running":
            return cast("str", row["status"])
        lock = await (
            await db.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (lock_key(thread_id),))
        ).fetchone()
        assert lock is not None  # SELECT 表达式总是返回一行。
        if not lock["acquired"]:
            return "running"
        # 上一个持锁者可能在第一次读取后刚完成；取得锁后重读，保留它写入的终态。
        row = await (
            await db.execute("SELECT status FROM agent_runs WHERE thread_id=%s", (thread_id,))
        ).fetchone()
        if not row:
            return "unknown"
        if row["status"] != "running":
            return cast("str", row["status"])
        await db.execute(
            "UPDATE agent_runs SET status='interrupted',updated_at=now() WHERE thread_id=%s",
            (thread_id,),
        )
        return "interrupted"
