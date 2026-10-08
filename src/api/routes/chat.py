"""聊天 HTTP 入口：校验会话、准备输入、提交执行。"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph as CompiledGraph
from sse_starlette.sse import EventSourceResponse  # noqa: TC002 (FastAPI 响应类型)

from api import run_store
from api.attachments import build_user_content
from api.chat_execution import stream_agent_events
from api.deps import current_context, get_agent, get_config
from api.history import load_thread_messages
from api.responses import ApiResult, success
from api.schemas.chat import ChatRequest, StreamChatRequest  # noqa: TC001 (FastAPI 请求体)
from api.sse import sse_response
from api.stream_runs import TooManyStreamRunsError, start_run
from api.task_cleanup import wait_for_cleanup
from api.utils.messages import text_of
from core.agent import run_once
from core.config import AppConfig
from core.context_type import MemoryContext
from core.human import pending, thread_lock
from core.llm import supports_vision
from core.sessions import ThreadAccessError, assert_thread_owner, new_thread_id

router = APIRouter()
Agent = Annotated[CompiledGraph[Any, MemoryContext, Any, Any], Depends(get_agent)]
Context = Annotated[MemoryContext, Depends(current_context)]
Config = Annotated[AppConfig, Depends(get_config)]


def _conversation(req: ChatRequest, ctx: MemoryContext) -> tuple[str, MemoryContext]:
    thread_id = req.thread_id or new_thread_id(ctx.user_id)
    try:
        assert_thread_owner(thread_id, ctx.user_id)
    except ThreadAccessError as exc:
        raise HTTPException(404, "对话不存在") from exc
    return thread_id, ctx.model_copy(
        update={"extra": {**ctx.extra, "approval_thread_id": thread_id}}
    )


@router.post("/chat", response_model=ApiResult[dict[str, Any]])
async def chat(
    req: ChatRequest, agent: Agent, ctx: Context, cfg: Config
) -> ApiResult[dict[str, Any]]:
    """非流式调用与流式调用使用相同的附件和会话互斥规则。"""
    thread_id, ctx = _conversation(req, ctx)
    lock = thread_lock(thread_id)
    if lock.locked():
        raise HTTPException(409, "当前任务正在执行")
    async with lock:
        lease = await run_store.claim(thread_id)
        status = "failed"
        try:
            user_input = await build_user_content(
                req.user_input, req.attachments, vision=supports_vision(cfg.llm), context=ctx
            )
            result = await run_once(agent, user_input, thread_id=thread_id, context=ctx)
            messages = result["messages"]
            reply = next(
                (
                    text_of(message.content)
                    for message in reversed(messages)
                    if isinstance(message, AIMessage)
                ),
                "",
            )
            waiting = await pending(agent, ctx, thread_id)
            status = "waiting" if any(waiting.values()) else "completed"
            return success(
                {
                    "thread_id": thread_id,
                    "reply": reply,
                    "message_count": len(messages),
                    "interactions": waiting,
                }
            )
        except asyncio.CancelledError:
            status = "interrupted"
            raise
        finally:
            await wait_for_cleanup(asyncio.create_task(run_store.finish(lease, thread_id, status)))


@router.post("/chat/stream")
async def chat_stream(
    req: StreamChatRequest, agent: Agent, ctx: Context, cfg: Config
) -> EventSourceResponse:
    """后台执行一轮对话；SSE 连接仅订阅结果。"""
    thread_id, ctx = _conversation(req, ctx)
    lock = thread_lock(thread_id)
    if lock.locked():
        raise HTTPException(409, "当前任务正在执行")
    await lock.acquire()
    try:
        lease = await run_store.acquire(thread_id)
        try:
            user_input = await build_user_content(
                req.user_input, req.attachments, vision=supports_vision(cfg.llm), context=ctx
            )
            history = await load_thread_messages(agent, thread_id)
        except BaseException:
            await wait_for_cleanup(asyncio.create_task(lease.close()))
            raise
    except BaseException:
        lock.release()
        raise

    # start_run 接管会话锁，包括提交失败和调用方取消时的释放。
    try:
        run = await start_run(
            thread_id,
            agent=agent,
            base_count=sum(message.role in ("user", "assistant") for message in history),
            user_input=req.user_input,
            events=stream_agent_events(
                agent=agent,
                user_input=user_input,
                user_text=req.user_input,
                thread_id=thread_id,
                include_tool_events=req.include_tool_events,
                context=ctx,
            ),
            lock=lock,
            lease=lease,
        )
    except TooManyStreamRunsError as exc:
        raise HTTPException(503, "后台任务已达上限，请稍后重试") from exc
    return sse_response(run.follow())
