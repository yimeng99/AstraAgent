"""Agent 运行时上下文（LangGraph runtime context）。

每次调用 agent 时由入口层构造，经 ``invoke(context=...)`` /
``astream_events(context=...)`` 传入。agent 内的节点、工具、sub-agent
都能通过 ``get_runtime_context()`` 读到它。

**用途**：身份与权限。业务工具据此判断"当前用户能不能做这件事"，
而不是靠 prompt 里写死的话术 —— prompt 可以被绕过，context 是代码级事实。

安全提醒：这里的字段来自 HTTP 层的 ``X-User-Id`` 等请求头，**尚未经过
可信鉴权**。任何人都能伪造这些头。因此本上下文只能用于「灰度 / 展示 /
开发期调试」，**不能**作为生产环境的唯一授权依据。接入 JWT / OIDC 后
需从 token 解析填充，且 roles / permissions 不得由客户端直接提供。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "MemoryContext",
    "get_runtime_context",
    "new_context",
]

#: 开发期 HTTP 入口使用的角色映射；模型自身只认可显式 permissions。
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"read", "write", "admin"}),
    "operator": frozenset({"read", "write"}),
    "viewer": frozenset({"read"}),
    "anonymous": frozenset(),
}


class MemoryContext(BaseModel):
    """传给 agent 的运行时上下文。

    Attributes:
        user_id: 调用者 ID，必填。
        tenant_id: 租户 ID，多租户隔离键；可为空。
        project_id: 项目 ID，项目级隔离键；可为空。
        roles: 角色集合；可为空集合。
        permissions: 显式授予的操作权限；可为空集合。
        request_token: 本次请求的凭证；可为空，不参与默认打印和序列化。
        extra: 业务方自定义扩展字段；**不要**往里塞凭证。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: str
    tenant_id: str = ""
    project_id: str = ""
    roles: frozenset[str] = Field(default_factory=frozenset)
    permissions: frozenset[str] = Field(default_factory=frozenset)
    extra: dict[str, object] = Field(default_factory=dict)
    # 凭证只供运行时工具使用，避免常规日志和 model_dump 暴露它。
    request_token: str = Field(default="", repr=False, exclude=True)

    def can(self, permission: str) -> bool:
        """是否拥有某权限。"""
        return permission in self.permissions


def new_context(
    *,
    user_id: str,
    tenant_id: str = "",
    project_id: str = "",
    roles: frozenset[str] = frozenset(),
    permissions: frozenset[str] = frozenset(),
    request_token: str = "",
    extra: dict[str, object] | None = None,
) -> MemoryContext:
    """构造上下文（入口层统一用这个，避免散落默认值）。"""
    return MemoryContext(
        user_id=user_id or "anonymous",
        tenant_id=tenant_id,
        project_id=project_id,
        roles=roles,
        permissions=permissions,
        request_token=request_token,
        extra=extra or {},
    )


def get_runtime_context() -> MemoryContext | None:
    """在 agent 内部（工具 / 节点 / sub-agent）取当前调用的上下文。

    Usage::

        ctx = get_runtime_context()
        if ctx is None or not ctx.can("write"):
            return "无权限执行该操作"

    Returns:
        当前 :class:`MemoryContext`；不在 agent 运行时内时返回 ``None``。
    """
    try:
        from langgraph.runtime import get_runtime
    except ImportError:
        # 老版本 LangGraph 没有该 API
        return None

    try:
        runtime = get_runtime()
    except Exception:
        return None

    return getattr(runtime, "context", None)
