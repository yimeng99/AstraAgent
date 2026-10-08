"""MCP 拦截器测试：角色校验、身份透传、超时。

拦截器是 P1 的横切层，全部逻辑都能在这里确定性验证 —— 不需要起 MCP 服务
（真实服务的连通性在 test_mcp_registry.py 里验）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_mcp_adapters.interceptors import MCPToolCallRequest

from core.context_type import MemoryContext
from core.mcp.config import MCPServerConfig
from core.mcp.interceptors import policy_interceptor

SERVER = "demo"


class _Runtime:
    """顶替 LangGraph 的 Runtime：拦截器只用到 ``.context``。"""

    def __init__(self, context: MemoryContext | None) -> None:
        if context is not None:
            self.context = context


def _config(**kwargs: Any) -> MCPServerConfig:
    base: dict[str, Any] = {"name": SERVER, "transport": "http", "url": "https://x/mcp"}
    base.update(kwargs)
    return MCPServerConfig(**base)


def _request(
    *, context: MemoryContext | None = None, headers: dict[str, str] | None = None
) -> MCPToolCallRequest:
    return MCPToolCallRequest(
        name=f"mcp__{SERVER}__add",
        args={"a": 1, "b": 2},
        server_name=SERVER,
        headers=headers,
        runtime=_Runtime(context) if context is not None else None,
    )


@pytest.fixture
def use_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    """让拦截器拿到指定配置（它内部是按服务名查注册表的）。"""

    def _install(config: MCPServerConfig) -> None:
        monkeypatch.setattr("core.mcp.registry.get_server_config", lambda name: config)

    return _install


async def _echo(request: MCPToolCallRequest) -> str:
    return "ok"


@pytest.mark.asyncio
async def test_allowed_role_passes_through(use_config):
    use_config(_config(allow_roles=("viewer",)))
    context = MemoryContext(user_id="u1", roles=frozenset({"viewer"}))

    calls: list[MCPToolCallRequest] = []

    async def handler(request: MCPToolCallRequest) -> str:
        calls.append(request)
        return "ok"

    assert await policy_interceptor(_request(context=context), handler) == "ok"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_denied_role_returns_error_result_without_calling_server(use_config):
    use_config(_config(allow_roles=("admin",)))
    context = MemoryContext(user_id="u1", roles=frozenset({"viewer"}))

    called = False

    async def handler(request: MCPToolCallRequest) -> str:
        nonlocal called
        called = True
        return "ok"

    result = await policy_interceptor(_request(context=context), handler)
    assert called is False, "没权限时绝不该真的去调外部服务"
    assert result.isError is True
    assert "没有调用该外部服务" in result.content[0].text


@pytest.mark.asyncio
async def test_missing_runtime_fails_closed(use_config):
    use_config(_config(allow_roles=("admin",)))
    result = await policy_interceptor(_request(context=None), _echo)
    assert result.isError is True


@pytest.mark.asyncio
async def test_no_role_restriction_allows_everyone(use_config):
    use_config(_config())
    result = await policy_interceptor(
        _request(context=MemoryContext(user_id="u1", roles=frozenset({"anonymous"}))), _echo
    )
    assert result == "ok"


@pytest.mark.asyncio
async def test_forward_identity_injects_headers(use_config):
    use_config(_config(forward_identity=True))
    context = MemoryContext(user_id="u9", tenant_id="org-7", roles=frozenset({"operator"}))

    seen: dict[str, str] = {}

    async def handler(request: MCPToolCallRequest) -> str:
        seen.update(request.headers or {})
        return "ok"

    await policy_interceptor(_request(context=context, headers={"X-Trace": "t"}), handler)
    assert seen["X-User-Id"] == "u9"
    assert seen["X-Org-Id"] == "org-7"
    assert seen["X-Tenant-Id"] == "org-7"
    assert seen["X-User-Roles"] == "operator"
    assert seen["X-User-Role"] == "operator"
    assert seen["X-Trace"] == "t", "原有的头不能被冲掉"


@pytest.mark.asyncio
async def test_identity_not_forwarded_when_disabled(use_config):
    use_config(_config())
    context = MemoryContext(user_id="u9", roles=frozenset({"operator"}))

    seen: dict[str, str] = {}

    async def handler(request: MCPToolCallRequest) -> str:
        seen.update(request.headers or {})
        return "ok"

    await policy_interceptor(_request(context=context), handler)
    assert seen == {}


@pytest.mark.asyncio
async def test_stdio_never_gets_identity_headers(use_config):
    # stdio 没有 HTTP 头这回事，加了反而会污染下游进程环境
    use_config(_config(transport="stdio", command="python", forward_identity=True))
    context = MemoryContext(user_id="u9", roles=frozenset({"operator"}))

    seen: dict[str, str] = {}

    async def handler(request: MCPToolCallRequest) -> str:
        seen.update(request.headers or {})
        return "ok"

    await policy_interceptor(_request(context=context), handler)
    assert seen == {}


@pytest.mark.asyncio
async def test_timeout_becomes_readable_failure(use_config):
    use_config(_config(call_timeout_seconds=0.05))

    async def slow(request: MCPToolCallRequest) -> str:
        await asyncio.sleep(1)
        return "ok"

    result = await policy_interceptor(_request(context=MemoryContext(user_id="u1")), slow)
    assert result.isError is True
    assert "没有响应" in result.content[0].text


@pytest.mark.asyncio
async def test_unexpected_error_propagates_to_framework(use_config):
    # 抛出去交给适配器 / LangGraph 的 handle_tool_errors 处理，保持行为一致
    use_config(_config())

    async def boom(request: MCPToolCallRequest) -> str:
        raise RuntimeError("server exploded")

    with pytest.raises(RuntimeError, match="server exploded"):
        await policy_interceptor(_request(context=MemoryContext(user_id="u1")), boom)


@pytest.mark.asyncio
async def test_unknown_server_is_passed_through(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.mcp.registry.get_server_config", lambda name: None)
    assert await policy_interceptor(_request(context=MemoryContext(user_id="u1")), _echo) == "ok"
