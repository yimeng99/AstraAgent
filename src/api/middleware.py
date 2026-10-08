"""HTTP 中间件：跨域、token 上下文和请求日志。"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import structlog
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace

from core.context_type import MemoryContext
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = get_logger(__name__)


async def _parse_request_token(token: str) -> MemoryContext:
    """验证 JWT 后返回用户上下文，由登录系统接入时补充。

    需校验签名、有效期及签发方/受众，再映射 user_id、tenant_id、
    project_id、roles 和 permissions；仅解码 payload 不能作为授权依据。
    """
    # TODO: 补充 JWT 校验及身份字段映射，不允许未实现时退回请求头身份。
    # raise NotImplementedError
    return MemoryContext(
        user_id="u-1001",
        project_id="1",
        roles=frozenset(),
        permissions=frozenset(),
    )


async def token_context(request: Request, call_next):
    authorization = request.headers.get("Authorization")
    if authorization is None:
        return await call_next(request)

    # scheme, _, token = authorization.partition(" ")
    # token = token.strip()
    # if scheme.lower() != "bearer" or not token:
    #     return error_response(
    #         401,
    #         "请提供有效的 Bearer token",
    #         headers={"WWW-Authenticate": "Bearer"},
    #     )
    # try:
    #     context = await _parse_request_token(token)
    #     if not isinstance(context, MemoryContext) or not context.user_id.strip():
    #         raise ValueError("JWT 解析结果缺少用户身份")
    # except NotImplementedError:
    #     return error_response(501, "JWT 校验逻辑尚未接入")
    # except ValueError:
    #     # 后续解析函数将无效或过期 token 统一转换为 ValueError，不返回凭证细节。
    #     return error_response(
    #         401,
    #         "登录凭证无效或已过期",
    #         headers={"WWW-Authenticate": "Bearer"},
    #     )
    # request.state.context = context.model_copy(update={"request_token": token})
    context = await _parse_request_token("")
    request.state.context = context
    return await call_next(request)


# ── request_id + 访问日志 ─────────────────────────────
async def access_log(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    tokens = structlog.contextvars.bind_contextvars(request_id=request_id)
    span = trace.get_current_span()
    span.set_attribute("request_id", request_id)
    start = time.perf_counter()
    logger.debug("http.request.start", method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        log = (
            logger.error
            if response.status_code >= 500
            else (logger.warning if response.status_code >= 400 else logger.info)
        )
        # call_next 返回时 SSE 仍在运行，不能把建立响应的耗时称为任务完成耗时。
        streaming = response.headers.get("content-type", "").startswith("text/event-stream")
        log(
            "http.stream.open" if streaming else "http.request.end",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )
        response.headers["x-request-id"] = request_id
        if span.get_span_context().is_valid:
            response.headers["x-trace-id"] = format(span.get_span_context().trace_id, "032x")
        return response
    except Exception:
        logger.exception("http.request.error", method=request.method, path=request.url.path)
        raise
    finally:
        structlog.contextvars.reset_contextvars(**tokens)


def register_middleware(app: FastAPI) -> None:
    """保持请求执行顺序：访问日志 → token 上下文 → CORS → 路由。"""
    # ── CORS（前端跨域调用）───────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",  # Next.js dev
            "http://localhost:5173",  # Vite dev
            # 生产环境改成具体域名
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "x-trace-id"],
    )
    app.middleware("http")(token_context)
    app.middleware("http")(access_log)
