"""FastAPI Depends（依赖注入）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

from core.config import AppConfig  # noqa: TC001  (FastAPI 运行时需真实类型解析 Depends)
from core.context_type import ROLE_PERMISSIONS, MemoryContext, new_context

if TYPE_CHECKING:
    from typing import Any

    from langgraph.graph.state import CompiledStateGraph as CompiledGraph

__all__ = ["current_context", "current_user_id", "get_agent", "get_config", "get_ready"]


def get_agent(request: Request) -> CompiledGraph[Any, MemoryContext, Any, Any]:
    """从 app.state 取出主 agent。

    Raises:
        503 Service Unavailable: agent 尚未就绪。
    """
    agent: CompiledGraph[Any, MemoryContext, Any, Any] | None = getattr(
        request.app.state, "agent", None
    )
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent 尚未就绪，请稍后重试",
        )
    return agent


def get_ready(request: Request) -> bool:
    """FastAPI 依赖：app 是否就绪。"""
    return bool(getattr(request.app.state, "ready", False))


def get_config(request: Request) -> AppConfig:
    """从 app.state 取出应用配置（lifespan 里写入）。

    Raises:
        503 Service Unavailable: 配置尚未就绪。
    """
    cfg: AppConfig | None = getattr(request.app.state, "cfg", None)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务配置尚未就绪，请稍后重试",
        )
    return cfg


def current_user_id(request: Request) -> str:
    """优先读取 token 中间件的用户身份，未接入时兼容开发期请求头。

    Returns:
        用户 ID 字符串；未提供时返回 ``"anonymous"``。
    """
    return current_context(request).user_id


def current_context(request: Request) -> MemoryContext:
    """构造本次请求的 agent 运行时上下文。

    优先读取 request.state.context，未带 token 时兼容开发期请求头。

    .. warning::
       这些头**全部可被客户端伪造**，故 roles 不构成可信授权依据。
       生产必须验证 JWT / OIDC token 后填充身份权限；保存 token 不等于验证它。
    """
    context = getattr(request.state, "context", None)
    if isinstance(context, MemoryContext):
        return context
    # 未带 token 的开发期请求暂时兼容旧入口，正式启用鉴权时应关闭此分支。
    # 兼容现有前端的单角色头；权限由入口映射，不从权限请求头直接授予。
    roles = frozenset(
        role.strip()
        for role in request.headers.get(
            "X-User-Roles", request.headers.get("X-User-Role", "viewer")
        ).split(",")
        if role.strip()
    )
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    return new_context(
        user_id=request.headers.get("X-User-Id", "") or "anonymous",
        tenant_id=request.headers.get(
            "X-Tenant-Id", request.headers.get("X-Org-Id", "default-org")
        ),
        project_id=request.headers.get("X-Project-Id", ""),
        roles=roles,
        permissions=frozenset().union(*(ROLE_PERMISSIONS.get(role, ()) for role in roles)),
        request_token=token.strip() if scheme.lower() == "bearer" else "",
    )
