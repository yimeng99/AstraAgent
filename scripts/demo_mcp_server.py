"""一个最小的 MCP 演示服务 —— 用来验证对接链路是否真的通。

它不是给生产用的，只是让 ``python -m core.mcp`` 有一个可以立刻连上的目标，
顺便演示两种传输怎么写配置。

**stdio**（本地子进程，最省事）::

    set MCP_SERVERS={"demo":{"transport":"stdio","command":"python","args":["scripts/demo_mcp_server.py"]}}
    python -m core.mcp

**http**（模拟"对接的 MCP 后端服务"）::

    python scripts/demo_mcp_server.py --http 8765          # 终端 A
    set MCP_SERVERS={"demo":{"transport":"http","url":"http://127.0.0.1:8765/mcp"}}
    python -m core.mcp
"""

from __future__ import annotations

import sys
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

#: 演示数据：查学生分数（和仓库里其他示例用同一套假数据）
_SCORES: dict[str, int] = {"张三": 91, "李四": 78, "王五": 85, "赵六": 66}

mcp = FastMCP("Demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """计算两个整数之和。"""
    return a + b


@mcp.tool()
def student_score(name: str) -> str:
    """按姓名查询学生的数学成绩（演示用的假数据）。

    Args:
        name: 学生姓名，例如「张三」。
    """
    score = _SCORES.get(name)
    if score is None:
        return f"没有找到 {name} 的成绩，已知名单：{'、'.join(_SCORES)}"
    return f"{name} 的数学成绩是 {score} 分"


@mcp.tool()
def whoami(ctx: Context) -> str:
    """回显本次调用携带的身份头（演示 forward_identity 身份透传）。"""
    request: Any = getattr(getattr(ctx, "request_context", None), "request", None)
    headers: Any = getattr(request, "headers", None) or {}
    return (
        f"user={headers.get('x-user-id', '(未透传)')} "
        f"org={headers.get('x-org-id', '-')} "
        f"role={headers.get('x-user-role', '-')}"
    )


def main() -> int:
    """按命令行参数决定起 stdio 还是 http。"""
    if "--http" in sys.argv:
        index = sys.argv.index("--http")
        port = int(sys.argv[index + 1]) if len(sys.argv) > index + 1 else 8765
        # 注意：必须改**同一个** mcp 实例的 host/port 再 run —— 新建一个
        # FastMCP 会把上面 @mcp.tool() 注册的工具全丢掉（踩过：工具数 0）。
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = port
        print(f"[demo-mcp] streamable-http 监听 http://127.0.0.1:{port}/mcp", flush=True)
        mcp.run(transport="streamable-http")
        return 0

    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
