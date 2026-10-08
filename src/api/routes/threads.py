"""Thread 管理端点。

列表数据来自两处并**合并**：:mod:`api.history`（checkpointer 里有消息的真实
对话）+ :data:`_REGISTERED`（刚建、还没发过消息的空对话）。空对话单独记一份而不是
往 checkpointer 写空 checkpoint —— 后者依赖 config 里的 ``checkpoint_ns`` 与完整
Checkpoint 内部结构，跨版本极易碎；等它有了第一条消息自然会出现在 checkpointer 里。

鉴权：thread_id 形如 ``{user_id}-{uuid}``，读路径都经 :func:`_assert_owner` 校验。

.. warning::
   这层隔离依赖「thread_id 内嵌 user_id」+ ``X-User-Id`` 请求头，而**任何人可伪造
   该头**。接入真实鉴权（JWT / OIDC）前它只能挡误访问，挡不住恶意越权。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from langgraph.graph.state import (
    CompiledStateGraph as CompiledGraph,  # noqa: TC002  (FastAPI 运行时需真实类型)
)
from langgraph.store.base import GetOp

from api.deps import current_user_id, get_agent
from api.history import (
    list_history_threads,
    load_thread_messages,
    make_title,
    owned_by_thread_id,
)
from api.responses import ApiResult, success
from api.run_failures import delete_failures
from api.schemas.chat import ArtifactInfo
from api.schemas.thread import Message, Thread, ThreadCreate, ThreadMessages, ThreadRename
from core.backend import get_store
from core.sessions import new_thread_id
from core.utils.logging import get_logger

logger = get_logger("api.threads")

router = APIRouter()

#: 已创建但还没有消息的对话：``{thread_id: (owner, 创建时间)}``。
#: 只活在进程内存里，供列表合并用；过期的会被回收（见 :func:`_prune_registered`）。
_REGISTERED: dict[str, tuple[str, datetime]] = {}

#: 空对话登记的有效期。超时且始终没有消息的，就从列表里消失 ——
#: 否则用户每点一次「+ 新对话」都会在侧边栏永久留下一条"（空对话）"。
_EMPTY_THREAD_TTL = timedelta(hours=12)


def _prune_registered() -> None:
    """清掉过期的空对话登记（不影响已经发过消息的对话）。"""
    if not _REGISTERED:
        return
    deadline = datetime.now(UTC) - _EMPTY_THREAD_TTL
    for tid in [t for t, (_, created) in _REGISTERED.items() if created < deadline]:
        _REGISTERED.pop(tid, None)


@router.get("/threads", response_model=ApiResult[list[Thread]])
async def list_threads(
    user_id: Annotated[str, Depends(current_user_id)],
    agent: Annotated[CompiledGraph[Any, Any, Any, Any], Depends(get_agent)],
) -> ApiResult[list[Thread]]:
    """列当前用户的所有对话（最近更新的在前）。"""
    out: dict[str, Thread] = {}

    # 1) checkpointer 里的真实对话（有消息）。user_id 必传 —— 否则任何人都能
    #    读到全部用户的对话历史。
    for s in await list_history_threads(agent, limit=100, user_id=user_id):
        out[s.id] = Thread(
            id=s.id,
            title=s.title,
            updated_at=_parse_ts(s.updated_at),
            message_count=s.message_count,
        )

    # 2) 刚创建、还没发过消息的空对话
    _prune_registered()
    for tid, (owner, _created) in _REGISTERED.items():
        if owner != user_id or tid in out:
            continue
        out[tid] = Thread(id=tid, title="新对话", message_count=0)

    # 自定义标题独立于模型消息，避免下一轮回复重新覆盖用户命名。
    titles = (
        await get_store().abatch(
            [GetOp(("thread_titles", user_id), thread.id) for thread in out.values()]
        )
        if out
        else []
    )
    for thread, saved in zip(out.values(), titles, strict=True):
        if saved:
            thread.title = saved.value["title"]

    # 3) 最近更新优先；空对话（无时间戳）排最后
    return success(
        sorted(
            out.values(),
            key=lambda t: t.updated_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
    )


def _parse_ts(raw: str) -> datetime | None:
    """把 checkpointer 的 ISO 时间串解析成 datetime；失败返回 None。"""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


@router.post("/threads", response_model=ApiResult[Thread], status_code=status.HTTP_201_CREATED)
async def create_thread(
    body: ThreadCreate,
    user_id: Annotated[str, Depends(current_user_id)],
) -> ApiResult[Thread]:
    """新建空对话。发起第一条消息后，它会进入 checkpointer。"""
    thread_id = new_thread_id(user_id)
    _REGISTERED[thread_id] = (user_id, datetime.now(UTC))
    now = datetime.now(UTC)
    logger.info("thread.created", thread_id=thread_id, user_id=user_id)
    return success(
        Thread(
            id=thread_id,
            title=body.title or "新对话",
            created_at=now,
            updated_at=now,
            message_count=0,
        )
    )


def _assert_owner(thread_id: str, user_id: str) -> None:
    """校验 thread 归属，不属于当前用户则 404。

    对**所有**按 ID 访问的端点都必须调用 —— 否则拿到别人的 thread_id
    就能读到其完整对话历史。

    Raises:
        HTTPException: 404（不区分"不存在"与"无权限"，避免泄露 ID 是否有效）。
    """
    if owned_by_thread_id(thread_id, user_id):
        return
    if _REGISTERED.get(thread_id) == user_id:
        return
    raise HTTPException(status_code=404, detail="对话不存在")


@router.get("/threads/{thread_id}", response_model=ApiResult[Thread])
async def get_thread(
    thread_id: str,
    user_id: Annotated[str, Depends(current_user_id)],
    agent: Annotated[CompiledGraph[Any, Any, Any, Any], Depends(get_agent)],
) -> ApiResult[Thread]:
    """取单个对话详情。"""
    _assert_owner(thread_id, user_id)
    messages = await load_thread_messages(agent, thread_id)
    saved = await get_store().aget(("thread_titles", user_id), thread_id)
    if messages:
        return success(
            Thread(
                id=thread_id,
                title=saved.value["title"] if saved else make_title(messages, thread_id),
                message_count=len(messages),
            )
        )
    return success(
        Thread(id=thread_id, title=saved.value["title"] if saved else "新对话", message_count=0)
    )


@router.get("/threads/{thread_id}/messages", response_model=ApiResult[ThreadMessages])
async def get_thread_messages(
    thread_id: str,
    user_id: Annotated[str, Depends(current_user_id)],
    agent: Annotated[CompiledGraph[Any, Any, Any, Any], Depends(get_agent)],
) -> ApiResult[ThreadMessages]:
    """取对话的完整消息历史（前端切换会话时调用）。"""
    _assert_owner(thread_id, user_id)
    raw = await load_thread_messages(agent, thread_id)
    return success(
        ThreadMessages(
            thread_id=thread_id,
            messages=[
                Message(
                    id=m.id,
                    role=m.role,
                    content=m.content,
                    reasoning=m.reasoning,
                    tools=list(m.tools),
                    failure=m.failure,
                    artifacts=[ArtifactInfo(**item) for item in m.artifacts],
                    attachments=[ArtifactInfo(**item) for item in m.attachments],
                )
                for m in raw
                if m.role in ("user", "assistant", "system", "tool")
            ],
        )
    )


@router.delete("/threads/{thread_id}", status_code=status.HTTP_200_OK)
async def delete_thread(
    thread_id: str,
    user_id: Annotated[str, Depends(current_user_id)],
) -> ApiResult[None]:
    """删除对话及其全部历史。"""
    _assert_owner(thread_id, user_id)

    from core.checkpointer import get_checkpointer

    _REGISTERED.pop(thread_id, None)
    try:
        await get_checkpointer().adelete_thread(thread_id)
    except Exception:
        logger.exception("thread.delete.failed", thread_id=thread_id)
        raise HTTPException(status_code=500, detail="删除失败") from None
    await get_store().adelete(("thread_titles", user_id), thread_id)
    await asyncio.to_thread(delete_failures, thread_id)
    from api.metrics import delete as delete_metrics

    await delete_metrics(thread_id)
    from api.subagent_runs import delete as delete_subagents

    await delete_subagents(thread_id)
    logger.info("thread.deleted", thread_id=thread_id, user_id=user_id)
    return success()


@router.patch("/threads/{thread_id}", response_model=ApiResult[Thread])
async def rename_thread(
    thread_id: str,
    body: ThreadRename,
    user_id: Annotated[str, Depends(current_user_id)],
    agent: Annotated[CompiledGraph[Any, Any, Any, Any], Depends(get_agent)],
) -> ApiResult[Thread]:
    """保存用户命名，沿用会话归属校验。"""
    _assert_owner(thread_id, user_id)
    if thread_id not in _REGISTERED and not await load_thread_messages(agent, thread_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    await get_store().aput(("thread_titles", user_id), thread_id, {"title": body.title.strip()})
    return await get_thread(thread_id, user_id, agent)
