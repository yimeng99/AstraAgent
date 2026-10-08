"""Server-Sent Events（SSE）响应助手。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sse_starlette.sse import EventSourceResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["sse_data", "sse_response"]


def sse_data(payload: dict[str, Any]) -> dict[str, str]:
    """构造一个 ``data:`` 字段，载荷 JSON 序列化。"""
    return {"data": json.dumps(payload, ensure_ascii=False)}


def sse_response(
    events: AsyncIterator[dict[str, Any]],
    *,
    ping_interval: float = 15.0,
) -> EventSourceResponse:
    """把 async event 迭代器包成 SSE 响应。

    Args:
        events: async iterator，每次 yield 一个 dict（已包含 type 字段）。
        ping_interval: 心跳间隔（秒），防代理超时。

    Example:
        async def gen():
            yield {"type": "message.delta", "delta": "你好"}
            yield {"type": "done"}

        return sse_response(gen())
    """

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        # 收尾标记由后台任务统一发（stream_runs 发布 "done"）：这里再补一个
        # 前端根本不认的 stream.end 只会制造"两种结束语义"。
        async for ev in events:
            yield sse_data(ev)

    return EventSourceResponse(event_generator(), ping=ping_interval)
