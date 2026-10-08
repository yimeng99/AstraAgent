"""挂起事项读取与断点恢复；恢复不是一条新的用户消息。"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import StateSnapshot
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api import run_store
from api.chat_execution import stream_agent_events
from api.deps import current_context, get_agent
from api.history import load_thread_messages
from api.responses import ApiResult, success
from api.run_failures import request_user_stop
from api.sse import sse_response
from api.stream_runs import TooManyStreamRunsError, active_run, start_run
from api.task_cleanup import wait_for_cleanup
from core.context_type import MemoryContext
from core.human import pending, prepare_approval_batch, prepare_resume, thread_lock
from core.sessions import ThreadAccessError, assert_thread_owner

router = APIRouter()
Context = Annotated[MemoryContext, Depends(current_context)]
Agent = Annotated[Any, Depends(get_agent)]


def _assert_owner(thread_id: str, user_id: str) -> None:
    try:
        assert_thread_owner(thread_id, user_id)
    except ThreadAccessError as exc:
        raise HTTPException(404, "对话不存在") from exc


class Resume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, min_length=1, max_length=200)
    ids: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, min_length=1, max_length=100
    )
    approve: bool | None = Field(default=None, strict=True)
    answer: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_target(self):
        if (self.id is None) == (self.ids is None):
            raise ValueError("请指定单项或批量审批事项")
        if self.ids is not None and (
            self.approve is None or self.answer is not None or len(set(self.ids)) != len(self.ids)
        ):
            raise ValueError("批量审批只接受明确的批准或拒绝")
        return self


def _uncertain_tools(snapshot: StateSnapshot) -> bool:
    # 下一节点可能是中间件；核对调用/结果，不能只看节点名是否为 tools。
    calls, results = set(), set()
    for message in snapshot.values.get("messages", []):
        if isinstance(message, AIMessage):
            calls.update(call["id"] for call in message.tool_calls)
        elif isinstance(message, ToolMessage):
            results.add(message.tool_call_id)
    return bool(calls - results) or any(task.state for task in snapshot.tasks)


@router.get("/threads/{thread_id}/interactions", response_model=ApiResult[object])
async def interactions(thread_id: str, agent: Agent, ctx: Context):
    return success(await pending(agent, ctx, thread_id))


@router.get("/threads/{thread_id}/metrics", response_model=ApiResult[object])
async def thread_metrics(thread_id: str, ctx: Context):
    from api.metrics import load

    _assert_owner(thread_id, ctx.user_id)
    return success(await load(thread_id))


@router.get("/threads/{thread_id}/subagents/{call_id}", response_model=ApiResult[object])
async def subagent_detail(thread_id: str, call_id: str, ctx: Context):
    from api.subagent_runs import load

    _assert_owner(thread_id, ctx.user_id)
    return success(await load(thread_id, call_id))


@router.get("/threads/{thread_id}/stream/status", response_model=ApiResult[object])
async def stream_status(thread_id: str, ctx: Context, agent: Agent):
    _assert_owner(thread_id, ctx.user_id)
    run = active_run(thread_id)
    state = "running" if run else await run_store.status(thread_id)
    snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    waiting = any(task.interrupts for task in snapshot.tasks)
    recoverable = (
        not run
        and state != "running"
        and state != "stopped"
        and bool(snapshot.next)
        and not waiting
    )
    uncertain_tools = _uncertain_tools(snapshot)
    return success(
        {
            "active": run is not None,
            "base_count": run.base_count if run else 0,
            "user_input": run.user_input if run else "",
            "state": "interrupted" if recoverable else state,
            "recoverable": recoverable,
            "requires_tool_confirmation": bool(uncertain_tools),
            "checkpoint_id": snapshot.config.get("configurable", {}).get("checkpoint_id", "")
            if snapshot.config
            else "",
        }
    )


@router.get("/threads/{thread_id}/stream")
async def follow_stream(thread_id: str, ctx: Context):
    _assert_owner(thread_id, ctx.user_id)
    run = active_run(thread_id)
    if run is None:
        raise HTTPException(404, "当前会话没有执行中的任务")
    return sse_response(run.follow())


@router.delete("/threads/{thread_id}/stream", response_model=ApiResult[object])
async def stop_stream(thread_id: str, ctx: Context):
    _assert_owner(thread_id, ctx.user_id)
    run = active_run(thread_id)
    if run is not None and run.task is not None:
        request_user_stop(run.task)
        # 停止确认须在记录落盘之后返回；断开本次 HTTP 不应再次打断保存。
        await asyncio.shield(asyncio.gather(run.task, return_exceptions=True))
    return success({"stopped": run is not None})


@router.post("/threads/{thread_id}/resume")
async def resume(thread_id: str, body: Resume, agent: Agent, ctx: Context):
    _assert_owner(thread_id, ctx.user_id)
    ctx = ctx.model_copy(update={"extra": {**ctx.extra, "approval_thread_id": thread_id}})
    lock = thread_lock(thread_id)
    if lock.locked():
        raise HTTPException(409, "当前任务正在执行，请勿重复提交")
    await lock.acquire()
    try:
        lease = await run_store.acquire(thread_id)
        try:
            history = await load_thread_messages(agent, thread_id)
            base_count = sum(item.role in ("user", "assistant") for item in history)
            command = (
                await prepare_approval_batch(agent, ctx, thread_id, body.ids, body.approve)
                if body.ids is not None
                else await prepare_resume(agent, ctx, thread_id, body.id, body.approve, body.answer)
            )
        except BaseException:
            await wait_for_cleanup(asyncio.create_task(lease.close()))
            raise
    except BaseException:
        lock.release()
        raise

    async def events():
        if command is None:
            yield {
                "type": "human.pending",
                "thread_id": thread_id,
                **await pending(agent, ctx, thread_id),
            }
        else:
            remaining = await pending(agent, ctx, thread_id)
            # 保存成功后才移除已恢复批次；未完成的其他审批继续留在弹窗中。
            resumed = set(command.resume)
            yield {
                "type": "human.pending",
                "thread_id": thread_id,
                **{
                    kind: [item for item in items if item["id"].rsplit(":", 1)[0] not in resumed]
                    for kind, items in remaining.items()
                },
            }
            async for event in stream_agent_events(
                agent=agent,
                user_input=command,
                user_text="",
                thread_id=thread_id,
                include_tool_events=True,
                context=ctx,
            ):
                yield event

    try:
        run = await start_run(
            thread_id,
            agent=agent,
            base_count=base_count,
            user_input="",
            events=events(),
            lock=lock,
            lease=lease,
        )
    except TooManyStreamRunsError as exc:
        raise HTTPException(503, "后台任务已达上限，请稍后重试") from exc
    return sse_response(run.follow())


class RecoverRun(BaseModel):
    checkpoint_id: str
    retry_tools: bool = False


@router.post("/threads/{thread_id}/recover")
async def recover_run(thread_id: str, body: RecoverRun, agent: Agent, ctx: Context):
    _assert_owner(thread_id, ctx.user_id)
    ctx = ctx.model_copy(update={"extra": {**ctx.extra, "approval_thread_id": thread_id}})
    lock = thread_lock(thread_id)
    if lock.locked():
        raise HTTPException(409, "当前任务正在执行")
    await lock.acquire()
    try:
        lease = await run_store.acquire(thread_id)
        try:
            if await run_store.status(thread_id) == "stopped":
                raise HTTPException(409, "用户已停止的任务不会自动恢复，请发送新的要求")
            snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
            checkpoint = (
                snapshot.config.get("configurable", {}).get("checkpoint_id", "")
                if snapshot.config
                else ""
            )
            if not snapshot.next or checkpoint != body.checkpoint_id:
                raise HTTPException(409, "检查点已变化或任务已结束，请刷新会话")
            if any(task.interrupts for task in snapshot.tasks):
                raise HTTPException(409, "请先处理待回答或待审批事项")
            if _uncertain_tools(snapshot) and not body.retry_tools:
                raise HTTPException(
                    409, "工具可能已经产生结果，请先核对会话文件，再确认是否重新执行"
                )
            history = await load_thread_messages(agent, thread_id)
        except BaseException:
            await wait_for_cleanup(asyncio.create_task(lease.close()))
            raise
    except BaseException:
        lock.release()
        raise

    async def events():
        async for event in stream_agent_events(
            agent=agent,
            user_input=None,
            user_text="",
            thread_id=thread_id,
            include_tool_events=True,
            context=ctx,
        ):
            yield event

    try:
        run = await start_run(
            thread_id,
            agent=agent,
            base_count=sum(item.role in ("user", "assistant") for item in history),
            user_input="",
            events=events(),
            lock=lock,
            lease=lease,
        )
    except TooManyStreamRunsError as exc:
        raise HTTPException(503, "后台任务已达上限，请稍后重试") from exc
    return sse_response(run.follow())
