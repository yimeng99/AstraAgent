"""运行一轮 agent，统一处理流事件、产物和失败输出的持久化。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from api.metrics import Collector
from api.run_failures import capture_failure
from api.stream_events import StreamState
from api.subagent_runs import SubagentRecorder
from core.agent import stream_once
from core.artifacts import take_pending
from core.human import pending
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langgraph.graph.state import CompiledStateGraph
    from langgraph.types import Command

    from api.stream_events import Event
    from core.agent import UserContent
    from core.context_type import MemoryContext

__all__ = ["stream_agent_events"]

logger = get_logger(__name__)


async def stream_agent_events(
    *,
    agent: CompiledStateGraph[Any, MemoryContext, Any, Any],
    user_input: UserContent | Command[Any] | None,
    user_text: str,
    thread_id: str,
    include_tool_events: bool,
    context: MemoryContext,
) -> AsyncIterator[Event]:
    """消费已准备好的输入；后台 stream_runs 负责发布唯一的 done 事件。

    失败记录使用 user_text 原话，避免把附件全文或恢复指令写进错误摘要。
    """
    state = StreamState(thread_id, include_tool_events)
    metrics = Collector(thread_id)
    subagents = SubagentRecorder(thread_id)
    yield {"type": "message.start", "thread_id": thread_id}

    try:
        await metrics.start()
        async for raw in stream_once(agent, user_input, thread_id=thread_id, context=context):
            # 统计和子任务记录必须先消费全部事件，主回复随后才隔离子任务流。
            await subagents.observe(raw)
            metrics.observe(raw)
            if statistics := await metrics.report():
                yield statistics
            for event in state.convert(raw):
                yield event

        for event in state.flush():
            yield event
        # 前端在 message.end 前收到产物，才能把文件挂到当前回复上。
        for event in _artifact_events(thread_id):
            yield event
        waiting = await pending(agent, context, thread_id)
        yield {"type": "human.pending", "thread_id": thread_id, **waiting}
        await subagents.finish("waiting" if any(waiting.values()) else "interrupted")
        yield state.end_event()
        if statistics := await metrics.report(finish=True):
            yield statistics
    except (Exception, asyncio.CancelledError) as exc:
        remaining = state.flush()
        # 先保存完整 partial，再交还控制权；消费方断开也不能丢失已生成内容。
        failure = await capture_failure(
            agent,
            thread_id,
            exc,
            stage=state.stage,
            tool_name=", ".join(state.active_tools.values()) or state.failed_tool,
            content=state.partial_text,
            reasoning=state.partial_reasoning,
            message_id=state.partial_id,
            user_input=user_text,
        )
        await subagents.finish("interrupted")
        logger.exception("chat.stream.error", thread_id=thread_id, error=str(exc))
        for event in remaining:
            yield event
        for event in _artifact_events(thread_id):
            yield event
        if statistics := await metrics.report(finish=True):
            yield statistics
        yield failure
        if isinstance(exc, asyncio.CancelledError):
            raise


def _artifact_events(thread_id: str) -> list[Event]:
    return [
        {"type": "artifact.created", "thread_id": thread_id, "artifact": artifact.to_dict()}
        for artifact in take_pending(thread_id)
    ]
