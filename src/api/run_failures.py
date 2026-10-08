"""保存会话的执行失败与未完成输出；独立于模型检查点，不改写工具调用协议。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4
from weakref import WeakKeyDictionary

from structlog.contextvars import get_contextvars

from core.config import PROJECT_ROOT
from core.security import safe_error_message
from core.sessions import owned_by_thread_id
from core.utils.logging import get_logger

logger = get_logger(__name__)
DATABASE = PROJECT_ROOT / "workspace" / "run-failures.sqlite3"
type CancellationReason = Literal["user_stop", "server_shutdown", "lease_lost"]
_cancellation_reasons: WeakKeyDictionary[asyncio.Task[Any], CancellationReason] = (
    WeakKeyDictionary()
)
_CANCELLATION_MESSAGES = {
    "user_stop": "已停止",
    "server_shutdown": "服务已关闭，任务执行中断",
    "lease_lost": "会话执行锁连接丢失，任务执行中断",
}


def request_cancellation(task: asyncio.Task[Any], reason: CancellationReason) -> None:
    """记录首次取消来源；重复请求不能打断正在进行的失败持久化。"""
    if task.done() or task.cancelling():
        return
    # 框架可能重新抛出不带参数的 CancelledError；来源独立于异常文本保存。
    _cancellation_reasons.setdefault(task, reason)
    task.cancel()


def request_user_stop(task: asyncio.Task[Any]) -> None:
    """用户明确要求停止当前执行。"""
    request_cancellation(task, "user_stop")


@contextmanager
def _connection():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE, timeout=10)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL, payload TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS failures_thread ON failures(thread_id)")
        yield db


def _save(thread_id: str, payload: dict) -> None:
    with _connection() as db:
        db.execute(
            "INSERT INTO failures(thread_id, payload) VALUES (?, ?)",
            (thread_id, json.dumps(payload, ensure_ascii=False)),
        )


def load_failures(thread_id: str) -> list[dict]:
    with _connection() as db:
        rows = db.execute(
            "SELECT payload FROM failures WHERE thread_id=? ORDER BY id", (thread_id,)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def delete_failures(thread_id: str) -> None:
    with _connection() as db:
        db.execute("DELETE FROM failures WHERE thread_id=?", (thread_id,))


def failure_threads(user_id: str, limit: int) -> dict[str, str]:
    prefix = user_id + "-"
    with _connection() as db:
        rows = db.execute(
            "SELECT thread_id, MAX(json_extract(payload, '$.failure.occurred_at')) "
            "FROM failures WHERE substr(thread_id, 1, length(?))=? "
            "GROUP BY thread_id ORDER BY MAX(id) DESC LIMIT ?",
            (prefix, prefix, limit),
        ).fetchall()
    return {thread: timestamp for thread, timestamp in rows if owned_by_thread_id(thread, user_id)}


async def capture_failure(
    agent,
    thread_id: str,
    exc: BaseException,
    *,
    stage: str = "agent",
    tool_name: str = "",
    content: str = "",
    reasoning: str = "",
    message_id: str = "",
    user_input: str = "",
) -> dict:
    reason = "execution_error"
    if isinstance(exc, asyncio.CancelledError):
        task = asyncio.current_task()
        if task is not None:
            reason = _cancellation_reasons.get(task, reason)
        message = _CANCELLATION_MESSAGES.get(reason, "任务执行中断")
    else:
        message = safe_error_message(exc)
    failure = {
        "id": str(uuid4()),
        "occurred_at": datetime.now(UTC).isoformat(),
        "error_type": type(exc).__name__,
        "reason": reason,
        "message": message,
        "stage": stage,
        "tool_name": tool_name,
        "request_id": str(get_contextvars().get("request_id", "")),
        "persisted": True,
        "input": user_input,
    }
    raw = []
    try:
        async with asyncio.timeout(5):
            snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
        raw = snapshot.values.get("messages", [])
    except Exception:
        # 检查点连接本身可能就是故障原因，仍须保存错误。
        logger.exception("chat.failure.checkpoint_unavailable", thread_id=thread_id)
    ids = [m.get("id", "") if isinstance(m, dict) else getattr(m, "id", "") for m in raw]
    if message_id and message_id in ids:
        content = reasoning = ""
    payload = {
        "failure": failure,
        "after_id": ids[-1] if ids else "",
        "after_count": len(raw),
        "content": content,
        "reasoning": reasoning,
    }
    try:
        # 在推送 error 事件之前提交，浏览器断开不会影响落盘。
        await asyncio.to_thread(_save, thread_id, payload)
    except Exception:
        failure["persisted"] = False
        logger.exception(
            "chat.failure.persistence_failed", thread_id=thread_id, failure_id=failure["id"]
        )
    return {
        "type": "error",
        "thread_id": thread_id,
        "error": failure["message"],
        "failure": failure,
    }
