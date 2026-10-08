"""当前用户的沙箱运行状态。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from api.deps import current_context
from api.responses import ApiResult, success
from core.context_type import MemoryContext
from core.sandbox.registry import get_sandbox_manager

router = APIRouter()


@router.get("/sandbox/status", response_model=ApiResult[dict[str, object]])
async def sandbox_status(ctx: Annotated[MemoryContext, Depends(current_context)]):
    """运行时长为本次进入 RUNNING 后的秒数，未知时为 null；available 表示运行且空闲。"""
    manager = get_sandbox_manager()
    if manager is None:
        return success(
            {
                "state": "DISABLED",
                "available": False,
                "busy": False,
                "created_at": None,
                "running_since": None,
                "running_seconds": None,
            }
        )
    return success(await run_in_threadpool(manager.get_status, ctx))
