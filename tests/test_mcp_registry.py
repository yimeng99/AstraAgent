"""MCP 注册表测试 —— 起一个**真的** stdio MCP 服务，而不是打桩。

要证明三件事（也就是 P0 的全部承诺）：
1. 工具能连上、被正确重命名成 ``mcp__{server}__{tool}``、能被调用；
2. 一个服务挂掉时，**只丢它自己**，其他服务和内置工具不受影响；
3. 关闭时把子进程和会话收拾干净。
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from core.mcp.config import MCPServerConfig
from core.mcp.registry import init_mcp, mcp_available, mcp_status, mcp_tools, shutdown_mcp

if TYPE_CHECKING:
    from pathlib import Path

SERVER_SOURCE = '''\
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """两数相加。"""
    return a + b


@mcp.tool()
def secret() -> str:
    """不该被白名单放行的工具。"""
    return "should not be exposed"


if __name__ == "__main__":
    mcp.run(transport="stdio")
'''


@pytest.fixture
def demo_server(tmp_path: Path) -> Path:
    path = tmp_path / "demo_mcp_server.py"
    path.write_text(SERVER_SOURCE, encoding="utf-8")
    return path


def _stdio_config(path: Path, **kwargs) -> MCPServerConfig:
    return MCPServerConfig(
        name="demo",
        transport="stdio",
        command=sys.executable,
        args=(str(path),),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_connect_and_call(demo_server: Path):
    try:
        tools = await init_mcp([_stdio_config(demo_server)])

        names = sorted(t.name for t in tools)
        assert names == ["mcp__demo__add", "mcp__demo__secret"]
        # 描述里标出来源服务，便于模型区分
        assert any("[MCP:demo]" in str(t.description) for t in tools)

        add_tool = next(t for t in tools if t.name == "mcp__demo__add")
        # langchain-core 1.x 的工具返回值是 content block 列表，不是裸值
        result = await add_tool.ainvoke({"a": 2, "b": 3})
        assert "5" in str(result)

        status = mcp_status()
        assert len(status) == 1
        assert status[0].ok and status[0].transport == "stdio"
        assert mcp_available()
    finally:
        await shutdown_mcp()

    assert mcp_tools() == []
    assert not mcp_available()


@pytest.mark.asyncio
async def test_tool_whitelist(demo_server: Path):
    try:
        tools = await init_mcp([_stdio_config(demo_server, include_tools=("add",))])
        assert [t.name for t in tools] == ["mcp__demo__add"]
    finally:
        await shutdown_mcp()


@pytest.mark.asyncio
async def test_broken_server_does_not_break_the_good_one(demo_server: Path):
    broken = MCPServerConfig(
        name="broken",
        transport="stdio",
        command="definitely-not-a-real-command-xyz",
        connect_timeout_seconds=20,
    )
    try:
        tools = await init_mcp([broken, _stdio_config(demo_server)])

        # 好的照常可用
        assert sorted(t.name for t in tools) == ["mcp__demo__add", "mcp__demo__secret"]

        by_name = {s.name: s for s in mcp_status()}
        assert by_name["demo"].ok
        assert not by_name["broken"].ok
        assert by_name["broken"].error  # 失败原因要能落到日志/自检里
    finally:
        await shutdown_mcp()


@pytest.mark.asyncio
async def test_invalid_config_is_skipped_not_raised():
    bad = MCPServerConfig(name="bad", transport="http", url="")
    try:
        tools = await init_mcp([bad])
        assert tools == []
        assert mcp_status()[0].ok is False
        assert "url" in mcp_status()[0].error
    finally:
        await shutdown_mcp()


@pytest.mark.asyncio
async def test_no_config_is_a_noop():
    assert await init_mcp([]) == []
    assert await shutdown_mcp() is None  # 幂等，重复关闭不报错


@pytest.mark.asyncio
async def test_interceptor_is_really_attached(demo_server: Path):
    """回归：拦截器必须真的挂在工具上。

    这里踩过一次坑 —— 为了复用长会话，我们是直接 ``load_mcp_tools(session)``，
    而它**不会**自动继承 ``MultiServerMCPClient`` 的 ``tool_interceptors``。
    漏传的后果是角色校验、身份透传、超时、调用日志全部静默失效（单测全绿，
    只有实机才暴露）。

    校验方式：把服务配成 ``allow_roles=["admin"]``，然后在 graph 外调用
    （拿不到运行时身份 → 应当 fail closed 拒绝）。拦截器没挂上就会拿到真实结果。
    """
    try:
        tools = await init_mcp([_stdio_config(demo_server, allow_roles=("admin",))])
        add_tool = next(t for t in tools if t.name == "mcp__demo__add")
        result = str(await add_tool.ainvoke({"a": 2, "b": 3}))

        assert "权限" in result, f"拦截器没生效，工具直接返回了：{result}"
        assert "= 5" not in result and "'text': '5'" not in result
    finally:
        await shutdown_mcp()
