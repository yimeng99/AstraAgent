"""Checkpointer 工厂（单例）。

* 配了 ``POSTGRES_URL`` 且连得上 → :class:`AsyncPostgresSaver`：对话历史落库，
  重启 / 热重载后仍在。
* 否则 → :class:`MemorySaver`：进程内，重启即丢（本地开发用）。

**为什么初始化是 async 的**：``AsyncPostgresSaver.from_conn_string`` 返回异步
context manager —— 和 :func:`core.backend._build_postgres_store` 是同一个坑：
CM 被 GC 掉会关闭底层连接，之后所有读写都报 "connection is closed"。所以由
:func:`core.agent.core_lifespan` 调 :func:`init_checkpointer` 建好、
:func:`close_checkpointer` 回收，:func:`get_checkpointer` 只负责取用。

**必须在真正使用它的事件循环里初始化**：PG 连接池绑定创建它的 loop，跨 loop
（例如先 ``asyncio.run(init)`` 再另起一个 ``asyncio.run`` 用）会报
"attached to a different loop"。

未初始化时 :func:`get_checkpointer` 给一个 ``MemorySaver`` 兜底（CLI / 测试等
不走 lifespan 的场景），此时不落库。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import MemorySaver

from core.security import safe_error_message
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = get_logger(__name__)

__all__ = ["close_checkpointer", "get_checkpointer", "init_checkpointer"]

_checkpointer: BaseCheckpointSaver | None = None
#: Postgres 版的异步 context manager，**必须活到 close_checkpointer**
_cm: AbstractAsyncContextManager[BaseCheckpointSaver] | None = None


def get_checkpointer() -> BaseCheckpointSaver:
    """取单例；未初始化时给内存版兜底（不落库）。"""
    return _checkpointer if _checkpointer is not None else MemorySaver()


async def list_checkpoint_threads(user_id: str | None, limit: int) -> dict[str, str]:
    """只枚举主会话最新检查点的标识与时间，不读取消息 blob 和子图状态。"""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from core.sessions import owned_by_thread_id

    saver = get_checkpointer()
    if isinstance(saver, AsyncPostgresSaver):
        # alist 会 fetchall 完整历史并反序列化 blob；列表只需要 checkpoint 元数据。
        # 使用 saver 的游标上下文，沿用其连接锁，读完即释放再加载会话摘要。
        async with saver._cursor() as cur:
            await cur.execute(
                """
                SELECT thread_id, checkpoint->>'ts' AS ts
                FROM (
                    SELECT DISTINCT ON (thread_id) thread_id, checkpoint
                    FROM checkpoints
                    WHERE checkpoint_ns = ''
                      AND (%s::text IS NULL OR (
                        left(thread_id, length(%s) + 1) = %s || '-'
                        AND substring(thread_id FROM length(%s) + 2)
                          ~ '^([0-9a-f]{8}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$'
                      ))
                    ORDER BY thread_id, checkpoint_id DESC
                ) latest
                ORDER BY checkpoint->>'ts' DESC
                LIMIT %s
                """,
                (user_id, user_id, user_id, user_id, limit),
            )
            return {row["thread_id"]: row["ts"] or "" for row in await cur.fetchall()}

    seen: dict[str, str] = {}
    async for item in saver.alist(None):
        config = (item.config or {}).get("configurable") or {}
        thread_id = config.get("thread_id")
        if not thread_id or config.get("checkpoint_ns") or thread_id in seen:
            continue
        if user_id is not None and not owned_by_thread_id(thread_id, user_id):
            continue
        seen[thread_id] = str(item.checkpoint.get("ts", ""))
        if len(seen) >= limit:
            break
    return seen


async def init_checkpointer() -> BaseCheckpointSaver:
    """建单例（幂等）。PG 连不上就退回内存版并告警，不让服务起不来。"""
    global _checkpointer, _cm

    if _checkpointer is not None:
        return _checkpointer

    url = (os.getenv("POSTGRES_URL") or "").strip()
    if url:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            cm = AsyncPostgresSaver.from_conn_string(url)
            saver = await cm.__aenter__()
            try:
                await saver.setup()  # 建表（首次必须）
            except Exception:
                await cm.__aexit__(None, None, None)
                raise
        except Exception as exc:
            logger.warning(
                "checkpointer.postgres.unavailable_fallback_memory",
                target=_safe_target(url),
                error=safe_error_message(exc),
                hint=(
                    "Windows 上 psycopg 异步需要 SelectorEventLoop；"
                    "uvicorn 用 --reload 启动时会自动选它（不带 --reload 则用 Proactor，会连不上）"
                ),
            )
        else:
            _cm, _checkpointer = cm, saver
            logger.info("checkpointer.postgres.ok", target=_safe_target(url))
            return saver

    _checkpointer = MemorySaver()
    logger.warning(
        "checkpointer.memory",
        reason="POSTGRES_URL 未配置或不可用：对话历史只存在进程内，重启即丢",
    )
    return _checkpointer


async def close_checkpointer() -> None:
    """释放连接池（幂等）。MemorySaver 无需释放。"""
    global _checkpointer, _cm

    cm, _cm = _cm, None
    _checkpointer = None
    if cm is None:
        return
    try:
        await cm.__aexit__(None, None, None)
        logger.info("checkpointer.closed")
    except Exception:  # pragma: no cover - 关闭阶段尽力而为
        logger.exception("checkpointer.close.failed")


def _safe_target(url: str) -> str:
    """日志里只留 host/db，别把口令打出去。"""
    return url.split("@")[-1] if "@" in url else url
