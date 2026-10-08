"""健康检查 + 元信息端点。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import current_user_id, get_ready
from api.responses import ApiResult, success
from core.utils.logging import get_logger

logger = get_logger("api.health")

router = APIRouter()


@router.get("/health")
async def health(ready: bool = Depends(get_ready)) -> ApiResult[dict[str, object]]:
    """健康检查：ready=True 表示 agent 已就绪可服务。"""
    return success(
        {
            "status": "ok" if ready else "starting",
            "agent_ready": ready,
        }
    )


@router.get("/auth/me")
async def auth_me(user_id: str = Depends(current_user_id)) -> ApiResult[dict[str, str]]:
    """当前用户（演示用，生产应接 JWT / OIDC）。"""
    return success({"user_id": user_id})
