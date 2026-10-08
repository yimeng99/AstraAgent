"""旧审批查询入口仍读取图断点；旧提交入口明确退役。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from api.deps import current_context, get_agent
from api.responses import ApiResult, success
from core.context_type import MemoryContext
from core.human import pending

router = APIRouter()


@router.get("/approvals", response_model=ApiResult[object])
async def list_approvals(
    thread_id: str,
    agent: Annotated[Any, Depends(get_agent)],
    ctx: Annotated[MemoryContext, Depends(current_context)],
):
    return success((await pending(agent, ctx, thread_id))["approvals"])


@router.post("/approvals/{approval_id}/decision", deprecated=True)
async def decide(approval_id: str):
    raise HTTPException(
        410, "旧审批接口已停用，请通过 /api/v1/threads/{thread_id}/resume 提交并恢复任务"
    )
