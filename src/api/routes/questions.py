"""待回答问题直接来自持久化的图断点。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.deps import current_context, get_agent
from api.responses import ApiResult, success
from core.context_type import MemoryContext
from core.human import pending

router = APIRouter()


@router.get("/questions", response_model=ApiResult[object])
async def list_questions(
    thread_id: str,
    agent: Annotated[Any, Depends(get_agent)],
    ctx: Annotated[MemoryContext, Depends(current_context)],
):
    return success((await pending(agent, ctx, thread_id))["questions"])
