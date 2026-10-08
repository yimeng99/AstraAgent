"""MCP 客户端注册表 —— 长会话生命周期 + 工具注册 + 失败隔离。

在 :func:`core.agent.core_lifespan` 里调 :func:`init_mcp` / :func:`shutdown_mcp`
（和沙箱那层对称）。三条设计决定：

* **开长会话**：适配器默认每次工具调用新建 session —— 远程 http 每次重新握手，
  stdio 更狠，每次 fork 一个子进程。所以启动时按服务开长会话（``client.session``），
  用 :class:`~contextlib.AsyncExitStack` 持有。
* **失败隔离**：连不上 / 超时 / 配置写错的服务只丢它自己，其余照常可用 ——
  MCP 是可选能力，不该拖垮整个应用。
* **工具改名** ``mcp__{server}__{tool}``：适配器自带的前缀用下划线拼接
  （``weather_search``），分不清哪段是服务名；不同服务可能同名，也会和内置工具
  （``run_python`` 等）撞，日志与 subagent 按名绑定都需要见名知义。
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.mcp.config import (
    HEADER_TRANSPORTS,
    MCPConfigError,
    MCPServerConfig,
    load_mcp_config,
)
from core.security import safe_error_message
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.tools import BaseTool

logger = get_logger(__name__)

__all__ = [
    "MCPServerStatus",
    "emits_tool_events",
    "get_server_config",
    "init_mcp",
    "mcp_available",
    "mcp_status",
    "mcp_tools",
    "server_of_tool",
    "shutdown_mcp",
]

#: 工具名前缀分隔符：``mcp__{server}__{tool}``
PREFIX = "mcp"


@dataclass(frozen=True, slots=True)
class MCPServerStatus:
    """单个 MCP 服务的连接结果（自检脚本和日志都用它）。"""

    name: str
    ok: bool
    tools: tuple[str, ...] = ()
    error: str = ""
    transport: str = ""


@dataclass
class _State:
    """模块级可变状态（放在一个对象里，避免满屏 global）。"""

    stack: AsyncExitStack | None = None
    tools: list[BaseTool] = field(default_factory=list)
    status: list[MCPServerStatus] = field(default_factory=list)
    #: 服务名 → 配置。拦截器要在调用时查角色白名单、透传开关、超时。
    configs: dict[str, MCPServerConfig] = field(default_factory=dict)


_state = _State()


def _sdk_available() -> bool:
    """适配器是否装上了。没装就降级（和沙箱缺 SDK 的处理一致）。"""
    try:
        import langchain_mcp_adapters.client  # noqa: F401
    except ImportError:
        return False
    return True


async def init_mcp(configs: Sequence[MCPServerConfig] | None = None) -> list[BaseTool]:
    """连接全部 MCP 服务并返回转换后的工具。

    Args:
        configs: 服务配置；不给则从环境变量读。

    Returns:
        LangChain 工具列表（名字已加 ``mcp__{server}__`` 前缀）。
        未配置、SDK 缺失、全部服务都连不上时返回空列表 —— 调用方无需判断。
    """
    await shutdown_mcp()  # 幂等：允许重复初始化（测试、热重载）

    try:
        targets = list(configs if configs is not None else load_mcp_config())
    except MCPConfigError as exc:
        logger.error("mcp.config.invalid", error=str(exc))
        _state.status = [MCPServerStatus(name="<config>", ok=False, error=str(exc))]
        return []

    enabled = [cfg for cfg in targets if cfg.enabled]
    if not enabled:
        logger.info("mcp.disabled", reason="未配置 MCP_SERVERS / MCP_CONFIG_FILE")
        return []

    if not _sdk_available():
        logger.warning("mcp.sdk.missing", reason="未安装 langchain-mcp-adapters")
        _state.status = [
            MCPServerStatus(name=cfg.name, ok=False, error="未安装 langchain-mcp-adapters")
            for cfg in enabled
        ]
        return []

    stack = AsyncExitStack()
    tools: list[BaseTool] = []
    status: list[MCPServerStatus] = []

    for cfg in enabled:
        problem = cfg.problem()
        if problem:
            logger.error("mcp.server.invalid", server=cfg.name, error=problem)
            status.append(MCPServerStatus(cfg.name, False, error=problem, transport=cfg.transport))
            continue

        try:
            server_tools = await _connect(stack, cfg)
        except Exception as exc:
            reason = _root_cause(exc)
            logger.warning(
                "mcp.server.unavailable",
                server=cfg.name,
                transport=cfg.transport,
                error=reason,
            )
            status.append(MCPServerStatus(cfg.name, False, error=reason, transport=cfg.transport))
            continue

        tools.extend(server_tools)
        status.append(
            MCPServerStatus(
                cfg.name,
                True,
                tools=tuple(t.name for t in server_tools),
                transport=cfg.transport,
            )
        )
        logger.info(
            "mcp.server.ok",
            server=cfg.name,
            transport=cfg.transport,
            tool_count=len(server_tools),
            tools=[t.name for t in server_tools],
        )

    _state.stack = stack
    _state.tools = tools
    _state.status = status
    _state.configs = {cfg.name: cfg for cfg in enabled}

    if not tools:
        # 一个都没连上：留着空 stack 没意义，立刻关掉（状态要留着给自检看）
        _state.stack = None
        await _close_quietly(stack)

    return tools


def _root_cause(exc: BaseException) -> str:
    """把 anyio 的 ``ExceptionGroup`` 剥到底层原因。

    适配器内部用 anyio 的 task group，任何连接失败都会被包成
    ``ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`` ——
    这句话对排查毫无帮助，真正有用的部分（Connection refused / 401 / 404）
    藏在最里层。自检脚本要能直接打印出可行动的原因，所以在这里剥干净。
    """
    current: BaseException = exc
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        inner = getattr(current, "exceptions", None)
        if inner:  # ExceptionGroup / BaseExceptionGroup：取第一个子异常继续剥
            current = inner[0]
            continue
        nxt = current.__cause__ or current.__context__
        if nxt is not None and nxt is not current:
            current = nxt
            continue
        break

    # safe_error_message 已经带上了类型名，别重复拼一遍
    message = safe_error_message(current).strip()
    if not message or message.startswith(f"{type(current).__name__}:"):
        return message or type(current).__name__
    return f"{type(current).__name__}: {message}"


async def _connect(stack: AsyncExitStack, cfg: MCPServerConfig) -> list[BaseTool]:
    """连一个服务，开长会话，加载并重命名它的工具。"""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools

    from core.mcp.interceptors import policy_interceptor

    interceptors = [policy_interceptor]
    client = MultiServerMCPClient({cfg.name: cfg.connection()}, tool_interceptors=interceptors)

    if cfg.forward_identity and cfg.transport in HEADER_TRANSPORTS:
        # 身份透传必须"按调用建会话"：适配器只有在该工具**没有绑定固定会话**时，
        # 才会用拦截器改过的 headers 去建新连接（见 langchain_mcp_adapters/tools.py
        # 的 execute_tool："If headers were modified, create a new connection"）。
        # 绑定长会话的话 headers 会被静默忽略 —— 实机排查出来的。
        # 代价：每次调用多一次握手。所以只对**显式打开 forward_identity** 的服务这样。
        raw_tools = await asyncio.wait_for(
            load_mcp_tools(
                None,
                connection=cfg.connection(),
                tool_interceptors=interceptors,
                server_name=cfg.name,
            ),
            timeout=cfg.connect_timeout_seconds,
        )
    else:
        session = await asyncio.wait_for(
            stack.enter_async_context(client.session(cfg.name)),
            timeout=cfg.connect_timeout_seconds,
        )
        # 注意：tool_interceptors 必须显式传。走 client.get_tools() 才会自动带上，
        # 而我们为了复用长会话直接调 load_mcp_tools(session)，它就只看自己的参数 ——
        # 漏传过一次，角色校验/超时/日志全部静默失效。
        raw_tools = await asyncio.wait_for(
            load_mcp_tools(
                session,
                connection=cfg.connection(),
                tool_interceptors=interceptors,
                server_name=cfg.name,
            ),
            timeout=cfg.connect_timeout_seconds,
        )
    return [_with_prefix(tool, cfg.name) for tool in raw_tools if cfg.allows(str(tool.name))]


def _with_prefix(tool: BaseTool, server: str) -> BaseTool:
    """改名为 ``mcp__{server}__{tool}``，并在描述里标出出处服务。"""
    description = str(tool.description or "").strip()
    return tool.model_copy(
        update={
            "name": f"{PREFIX}__{server}__{tool.name}",
            "description": f"[MCP:{server}] {description}".strip(),
        }
    )


async def shutdown_mcp() -> None:
    """关闭全部 MCP 会话（stdio 子进程在这里被回收）。"""
    stack, _state.stack = _state.stack, None
    _state.tools = []
    _state.status = []
    _state.configs = {}

    if stack is None:
        return
    await _close_quietly(stack)


async def _close_quietly(stack: AsyncExitStack) -> None:
    """关掉 exit stack；关闭期报错不值得影响进程退出。"""
    try:
        await stack.aclose()
        logger.info("mcp.shutdown.ok")
    except Exception:
        logger.exception("mcp.shutdown.failed")


def mcp_tools() -> list[BaseTool]:
    """当前已注册的 MCP 工具（未初始化时为空）。"""
    return list(_state.tools)


def mcp_status() -> list[MCPServerStatus]:
    """各服务的连接状态（自检脚本用）。"""
    return list(_state.status)


def mcp_available() -> bool:
    """是否至少有一个 MCP 服务连上了。"""
    return bool(_state.tools)


def get_server_config(name: str) -> MCPServerConfig | None:
    """按服务名取配置（拦截器用）。未接入的服务返回 ``None``。"""
    return _state.configs.get(name)


def server_of_tool(tool_name: str) -> str | None:
    """``mcp__{server}__{tool}`` → ``{server}``；不是 MCP 工具则返回 ``None``。"""
    prefix = f"{PREFIX}__"
    if not tool_name.startswith(prefix):
        return None
    remainder = tool_name[len(prefix) :]
    server, separator, _tool = remainder.partition("__")
    if not separator or not server:
        return None
    return server


def emits_tool_events(tool_name: str) -> bool:
    """该工具调用时要不要推 tool.start / tool.end。

    只对 MCP 工具、且服务配置里没关掉时返回 True —— 外部服务往往要等几秒，
    界面得有个"正在查询"的反馈，否则用户以为卡死。
    """
    server = server_of_tool(tool_name)
    if server is None:
        return False
    config = _state.configs.get(server)
    return bool(config and config.emit_events)
