"""MCP 连通性自检：``python -m core.mcp``。

配好 ``MCP_SERVERS`` / ``MCP_CONFIG_FILE`` 后先跑这个，别一上来就开对话 ——
MCP 的报错在 agent 里会被包成工具消息，很难看清是谁没连上。

退出码：0 全部可用；1 有服务连不上；2 配置本身不合法 / 没配。
"""

from __future__ import annotations

import asyncio
import sys

from core.mcp.config import MCPConfigError, MCPServerConfig, load_mcp_config
from core.mcp.registry import init_mcp, mcp_status, shutdown_mcp
from core.utils.logging import get_logger

logger = get_logger(__name__)

_EXAMPLE = """\
配置示例（二选一）：

  # 1) 环境变量：一行 JSON
  set MCP_SERVERS={"docs":{"transport":"http","url":"https://mcp.example.com/mcp",\
"headers":{"Authorization":"Bearer ${DOCS_MCP_TOKEN}"}}}

  # 2) 配置文件
  set MCP_CONFIG_FILE=config/mcp.json

支持的传输：stdio（本地子进程）、http（streamable HTTP，远程服务）、sse（老式远程）。
"""


def _print_config(configs: list[MCPServerConfig]) -> None:
    print(f"发现 {len(configs)} 个服务配置：")
    for cfg in configs:
        flag = "启用" if cfg.enabled else "已禁用"
        detail = f"{cfg.command} {' '.join(cfg.args)}".strip() if cfg.is_stdio else cfg.url
        print(f"  - {cfg.name} [{cfg.transport}/{flag}] {detail}")
        if cfg.include_tools:
            print(f"      白名单: {', '.join(cfg.include_tools)}")
        if cfg.exclude_tools:
            print(f"      黑名单: {', '.join(cfg.exclude_tools)}")


async def _main() -> int:
    try:
        configs = load_mcp_config()
    except MCPConfigError as exc:
        print(f"[配置错误] {exc}\n\n{_EXAMPLE}")
        return 2

    if not configs:
        print(f"没有配置任何 MCP 服务。\n\n{_EXAMPLE}")
        return 2

    _print_config(configs)
    print("\n正在连接…")

    tools = await init_mcp(configs)
    try:
        statuses = mcp_status()
        print(f"\n{'服务':<20} {'结果':<8} 工具")
        print("-" * 72)
        for status in statuses:
            head = "✓ 可用" if status.ok else "✗ 失败"
            print(f"{status.name:<20} {head:<8} {len(status.tools)} 个")
            for name in status.tools:
                print(f"{'':<29}- {name}")
            if status.error:
                print(f"{'':<29}原因: {status.error}")

        print(f"\n合计可用工具 {len(tools)} 个")
    finally:
        await shutdown_mcp()

    failed = [s for s in statuses if not s.ok]
    if not tools:
        print("\n没有任何服务可用 —— 上面每个服务的「原因」就是排查入口。")
        return 1
    if failed:
        print(f"\n有 {len(failed)} 个服务不可用（其余照常可用，不影响对话）。")
        return 1
    print("\n全部服务连接正常。")
    return 0


def main() -> int:
    """同步入口（``python -m core.mcp``）。"""
    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
