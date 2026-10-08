"""把正在运行的 Agent 与浏览器 SSE 连接分开。仅管理当前进程内的活动任务。"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import psycopg

from api import run_store
from api.run_failures import capture_failure, request_cancellation
from api.task_cleanup import wait_for_cleanup
from core.utils.logging import get_logger

logger = get_logger(__name__)

MAX_ACTIVE_RUNS = 8
MAX_REPLAY_BYTES = 2 * 1024 * 1024
RunStatus = Literal["completed", "waiting", "failed", "stopped", "interrupted"]


class TooManyStreamRunsError(Exception):
    """当前进程已达到后台 Agent 任务上限。"""


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langgraph.graph.state import CompiledStateGraph


@dataclass
class StreamRun:
    """一个后台生产者及其有界回放；每个 SSE 连接拥有独立读取位置。"""

    thread_id: str
    base_count: int
    user_input: str
    events: deque[tuple[dict[str, Any], int]] = field(default_factory=deque)
    first_sequence: int = 0
    replay_bytes: int = 0
    replay_limit_bytes: int = MAX_REPLAY_BYTES
    finished: bool = False
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] = field(init=False, repr=False)

    async def publish(self, event: dict[str, Any]) -> None:
        """发布已构造好的 SSE 载荷，超出回放容量时明确通知订阅者。"""
        size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
        if size > self.replay_limit_bytes:
            event = {"type": "stream.truncated", "thread_id": self.thread_id}
            size = len(json.dumps(event).encode("utf-8"))
        async with self.changed:
            self.events.append((event, size))
            self.replay_bytes += size
            while self.replay_bytes > self.replay_limit_bytes and len(self.events) > 1:
                _, removed_size = self.events.popleft()
                self.replay_bytes -= removed_size
                self.first_sequence += 1
            self.changed.notify_all()

    async def follow(self) -> AsyncIterator[dict[str, Any]]:
        """每个连接独立从头回放；断开只结束这个订阅者。"""
        position = 0

        def has_updates() -> bool:
            return position < self.first_sequence + len(self.events) or self.finished

        while True:
            async with self.changed:
                await self.changed.wait_for(has_updates)
                truncated = position < self.first_sequence
                position = max(position, self.first_sequence)
                batch = [event for event, _ in list(self.events)[position - self.first_sequence :]]
                position = self.first_sequence + len(self.events)
                finished = self.finished
            if truncated:
                yield {"type": "stream.truncated", "thread_id": self.thread_id}
            for event in batch:
                yield event
            if finished:
                return


_runs: dict[str, StreamRun] = {}
_starting: set[str] = set()


def active_run(thread_id: str) -> StreamRun | None:
    """查找当前进程中仍可订阅的任务。"""
    run = _runs.get(thread_id)
    return run if run is not None and not run.finished else None


async def start_run(
    thread_id: str,
    *,
    base_count: int,
    user_input: str,
    events: AsyncIterator[dict[str, Any]],
    lock: asyncio.Lock,
    agent: CompiledStateGraph[Any, Any, Any, Any],
    lease: psycopg.AsyncConnection[dict[str, Any]] | None = None,
) -> StreamRun:
    """接管调用方持有的会话锁；失败或结束时也由本模块释放。

    传入的 lease 仅持有会话租约，运行记录在容量检查通过后建立。
    输入流提供展示事件，error 必须来自 capture_failure，且不提供 done。
    返回前生产者已经启动，调用方可以立即取消 task 而不会跳过资源清理。
    """
    run = StreamRun(thread_id=thread_id, base_count=base_count, user_input=user_input)
    try:
        if len(_runs) + len(_starting) >= MAX_ACTIVE_RUNS:
            raise TooManyStreamRunsError
        # 在连接数据库之前占位，并发请求不会同时通过容量检查。
        _starting.add(thread_id)
        try:
            if lease is None:
                lease = await run_store.claim(thread_id)
            else:
                await run_store.begin(lease, thread_id)
        except BaseException:
            _starting.remove(thread_id)
            raise
    except BaseException:
        await wait_for_cleanup(asyncio.create_task(_release_rejected_run(lease, lock)))
        raise

    started = asyncio.Event()
    run.task = asyncio.create_task(
        _produce(run, events, lease, lock, agent, started), name=f"chat:{thread_id}"
    )
    try:
        await started.wait()
    except asyncio.CancelledError:
        # 未首次运行的 coroutine 收到 cancel 不会进入 finally，先完成资源移交。
        await wait_for_cleanup(asyncio.create_task(_cancel_starting_run(run, started)))
        raise
    return run


async def _cancel_starting_run(run: StreamRun, started: asyncio.Event) -> None:
    await started.wait()
    run.task.cancel()
    await asyncio.gather(run.task, return_exceptions=True)


async def _release_rejected_run(
    lease: psycopg.AsyncConnection[dict[str, Any]] | None, lock: asyncio.Lock
) -> None:
    try:
        if lease is not None:
            await lease.close()
    finally:
        lock.release()


async def _watch_lease(run: StreamRun, lease: psycopg.AsyncConnection[dict[str, Any]]) -> None:
    try:
        while True:
            await asyncio.sleep(5)
            async with asyncio.timeout(5):
                await lease.execute("SELECT 1")
    except (psycopg.Error, TimeoutError):
        logger.exception("chat.run.lease_lost", thread_id=run.thread_id)
        request_cancellation(run.task, "lease_lost")


def _failure_status(event: dict[str, Any]) -> RunStatus:
    failure = event["failure"]
    if failure["reason"] == "user_stop":
        return "stopped"
    return "interrupted" if failure["error_type"] == "CancelledError" else "failed"


async def _produce(
    run: StreamRun,
    events: AsyncIterator[dict[str, Any]],
    lease: psycopg.AsyncConnection[dict[str, Any]],
    lock: asyncio.Lock,
    agent: CompiledStateGraph[Any, Any, Any, Any],
    started: asyncio.Event,
) -> None:
    _runs[run.thread_id] = run
    _starting.remove(run.thread_id)
    watcher = asyncio.create_task(_watch_lease(run, lease))
    status: RunStatus = "completed"
    started.set()
    try:
        async for event in events:
            if event["type"] == "error":
                status = _failure_status(event)
            elif event["type"] == "human.pending":
                status = "waiting" if event["approvals"] or event["questions"] else "completed"
            await run.publish(event)
    except (Exception, asyncio.CancelledError) as exc:
        # 正常执行层携带部分正文保存失败；此处只接住未处理的边界异常。
        if status not in ("failed", "stopped", "interrupted"):
            status = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
            logger.exception("chat.background_stream.error", thread_id=run.thread_id)
            failure = await capture_failure(agent, run.thread_id, exc, user_input=run.user_input)
            status = _failure_status(failure)
            await run.publish(failure)
        if isinstance(exc, asyncio.CancelledError):
            raise
    finally:
        cleanup = asyncio.create_task(_finish_run(run, watcher, lease, lock, status))
        await wait_for_cleanup(cleanup)


async def _finish_run(
    run: StreamRun,
    watcher: asyncio.Task[None],
    lease: psycopg.AsyncConnection[dict[str, Any]],
    lock: asyncio.Lock,
    status: RunStatus,
) -> None:
    watcher.cancel()
    await asyncio.gather(watcher, return_exceptions=True)
    try:
        await run_store.finish(lease, run.thread_id, status)
    except psycopg.Error:
        logger.exception("chat.run.finish_failed", thread_id=run.thread_id)
    finally:
        await run.publish({"type": "done", "thread_id": run.thread_id})
        async with run.changed:
            run.finished = True
            run.changed.notify_all()
        del _runs[run.thread_id]
        lock.release()


async def shutdown_runs() -> None:
    """取消后台生产者，等待失败记录与资源清理完成。"""
    tasks = [run.task for run in list(_runs.values()) if not run.task.done()]
    for task in tasks:
        request_cancellation(task, "server_shutdown")
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
