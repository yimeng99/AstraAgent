"""MCP 工具调用的横切关注点：角色校验、身份透传、超时、调用日志。

* **用拦截器而不是给每个工具包一层**：适配器的 ``MCPToolCallRequest`` 同时带着
  ``headers``（可改）、``server_name``（可查配置）、``runtime``（能拿到
  :class:`~core.context_type.MemoryContext`），一个拦截器就能办完全部四件事，
  且工具对象本身不动 —— 不会破坏 ``args_schema``。
* **角色校验只能在调用时做**：agent 的工具清单是启动时构建的全局对象，不认识
  "当前是谁"；身份是每次请求才有的。写法与 :mod:`core.sandbox.tools` 一致。
* **身份透传**：把 ``X-User-Id`` / ``X-Org-Id`` / ``X-User-Role`` 带给下游，
  由它做行级鉴权，比我们在这一侧猜权限准。代价是适配器会**为该次调用新建连接**，
  所以只对显式打开 ``forward_identity`` 的服务生效。
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import TYPE_CHECKING

from mcp.types import CallToolResult, TextContent

from core.mcp.config import HEADER_TRANSPORTS
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain_mcp_adapters.interceptors import MCPToolCallRequest

    from core.context_type import MemoryContext
    from core.mcp.config import MCPServerConfig

logger = get_logger(__name__)

__all__ = ["policy_interceptor"]

#: 透传身份时带的请求头（下游服务照这几个键取人）
IDENTITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-User-Id", "user_id"),
    ("X-Org-Id", "tenant_id"),
    ("X-Tenant-Id", "tenant_id"),
    ("X-Project-Id", "project_id"),
)


async def policy_interceptor(
    request: MCPToolCallRequest,
    handler: Callable[[MCPToolCallRequest], Awaitable[object]],
) -> object:
    """角色校验 → 身份透传 → 超时 → 调用日志。"""
    # 延迟导入避免与 registry 形成循环
    from core.mcp.registry import get_server_config

    config = get_server_config(request.server_name)
    if config is None:  # 理论上不会发生
        return await handler(request)

    context = _context_of(request.runtime)

    denied = _role_denial(config, context)
    if denied is not None:
        logger.warning(
            "mcp.tool.denied",
            server=request.server_name,
            tool=request.name,
            roles=sorted(context.roles) if context else [],
            user_id=getattr(context, "user_id", None),
        )
        return _failure(denied)

    if config.forward_identity and context is not None and config.transport in HEADER_TRANSPORTS:
        request = request.override(
            headers={**(request.headers or {}), **_identity_headers(context)}
        )

    started = perf_counter()
    try:
        result = await asyncio.wait_for(handler(request), timeout=config.call_timeout_seconds)
    except TimeoutError:
        logger.warning(
            "mcp.tool.timeout",
            server=request.server_name,
            tool=request.name,
            timeout_seconds=config.call_timeout_seconds,
        )
        return _failure(
            f"外部服务在 {config.call_timeout_seconds:.0f} 秒内没有响应，本次调用已中断。"
            "可以稍后重试，或改用其他方式获取这部分信息。"
        )
    except Exception as exc:
        logger.warning(
            "mcp.tool.failed",
            server=request.server_name,
            tool=request.name,
            elapsed_ms=round((perf_counter() - started) * 1000),
            error=type(exc).__name__,
        )
        raise  # 交给适配器 / LangGraph 的 handle_tool_errors 统一转成错误工具消息

    logger.info(
        "mcp.tool.call",
        server=request.server_name,
        tool=request.name,
        elapsed_ms=round((perf_counter() - started) * 1000),
        roles=sorted(context.roles) if context else [],
        user_id=getattr(context, "user_id", None),
        forwarded_identity=bool(config.forward_identity),
    )
    return result


def _context_of(runtime: object | None) -> MemoryContext | None:
    """从 LangGraph 运行时取本项目的上下文。

    取不到（比如工具在 graph 外被直接调用）返回 ``None`` —— 此时若服务配了
    ``allow_roles``，按"无权限"处理（fail closed）。
    """
    from core.context_type import MemoryContext

    context = getattr(runtime, "context", None)
    return context if isinstance(context, MemoryContext) else None


def _role_denial(config: MCPServerConfig, context: MemoryContext | None) -> str | None:
    """角色不满足则返回给模型看的拒绝文案，满足返回 ``None``。"""
    if not config.allow_roles:
        return None
    roles = context.roles if context else frozenset()
    if roles.intersection(config.allow_roles):
        return None
    return (
        f"当前身份（{', '.join(sorted(roles)) or '未知'}）没有调用该外部服务的权限，已拒绝本次请求。"
        "如果确实需要，请让有权限的同事操作，或联系管理员调整权限。"
    )


def _identity_headers(context: MemoryContext) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header, attribute in IDENTITY_HEADERS:
        value = getattr(context, attribute, "")
        if value:
            headers[header] = str(value)
    if context.roles:
        headers["X-User-Roles"] = ",".join(sorted(context.roles))
        # 旧下游仅认单角色；多角色不擅自选一个，交给下游明确处理。
        if len(context.roles) == 1:
            headers["X-User-Role"] = next(iter(context.roles))
    return headers


def _failure(message: str) -> CallToolResult:
    """构造 MCP 原生风格的"调用失败"结果。

    ``isError=True`` 会被适配器转成 ``status="error"`` 的工具消息交给模型，
    模型据此向用户解释，而不是把异常炸到整轮对话上。
    """
    return CallToolResult(content=[TextContent(type="text", text=message)], isError=True)
