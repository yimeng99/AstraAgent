"""把工具的可恢复失败交给模型，程序错误保留原始异常。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import httpx
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException
from pydantic import ValidationError

from core.security import safe_error_message
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.types import Command

logger = get_logger(__name__)
_RETRY_READS = frozenset({"ls", "read_file", "glob", "grep", "query_ragwiki"})
_RECOVERABLE_ERRORS = (ToolException, ValidationError, OSError, httpx.HTTPError)
_TRANSIENT_ERRORS = (TimeoutError, ConnectionError, httpx.TransportError)


class ToolErrorMiddleware(AgentMiddleware):
    """只读请求可重试网络故障；有副作用的操作永不自动重放。"""

    @staticmethod
    def _retry(request: ToolCallRequest, exc: Exception, attempt: int) -> bool:
        return (
            attempt < 2
            and request.tool_call["name"] in _RETRY_READS
            and isinstance(exc, _TRANSIENT_ERRORS)
        )

    @staticmethod
    def _failure(request: ToolCallRequest, exc: Exception) -> ToolMessage:
        name = request.tool_call["name"]
        logger.warning(
            "agent.tool.failed", tool=name, call_id=request.tool_call["id"], exc_info=True
        )
        return ToolMessage(
            name=name,
            tool_call_id=request.tool_call["id"],
            status="error",
            content=safe_error_message(exc),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """同步工具边界；没有列为可恢复的异常直接交给运行层。"""
        attempt = 0
        while True:
            try:
                return handler(request)
            except _RECOVERABLE_ERRORS as exc:
                if not self._retry(request, exc, attempt):
                    return self._failure(request, exc)
                attempt += 1
                logger.warning("agent.tool.retry", tool=request.tool_call["name"], attempt=attempt)
                time.sleep(0.5 * attempt)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """异步工具边界；图中断和取消不属于工具失败。"""
        attempt = 0
        while True:
            try:
                return await handler(request)
            except _RECOVERABLE_ERRORS as exc:
                if not self._retry(request, exc, attempt):
                    return self._failure(request, exc)
                attempt += 1
                logger.warning("agent.tool.retry", tool=request.tool_call["name"], attempt=attempt)
                await asyncio.sleep(0.5 * attempt)
