"""主智能体工厂。

调用 :func:`build_core_agent` 构造一个 ``CompiledGraph``，可直接 ``invoke`` / ``stream``。

详见 :mod:`docs/design/architecture` §2 编排层。
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langgraph.types import Command

from core import tools as sys_tools
from core.backend import get_backend
from core.checkpointer import get_checkpointer
from core.context_type import MemoryContext
from core.execution_budget import ExecutionBudgetMiddleware
from core.human import HumanInteractionMiddleware, ask_user
from core.llm import build_llm_client
from core.mcp.registry import shutdown_mcp
from core.model_retry import model_timeout_retry
from core.prompts import MCP_NOTICE, SYSTEM_PROMPT
from core.sandbox.registry import sandbox_available
from core.sandbox.skills import SKILLS_ROOT
from core.sessions import assert_thread_owner
from core.subagent import BUILTIN_SUBAGENTS
from core.subagent.general_worker import GENERAL_WORKER_PROMPT
from core.tool_errors import ToolErrorMiddleware
from core.tracing import capture_io, operation
from core.utils.logging import get_logger
from ragwiki.tools import query_ragwiki

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from deepagents.middleware.subagents import SubAgent
    from langchain_core.tools import BaseTool
    from langgraph.graph.state import CompiledStateGraph as CompiledGraph

    from core.config import AppConfig

logger = get_logger(__name__)

__all__ = ["build_core_agent", "close_agent_resources", "core_lifespan", "run_once", "stream_once"]

#: 用户消息内容：纯文本，或 OpenAI 风格的多模态 content 块列表
#: （``[{"type": "text", ...}, {"type": "image_url", ...}]``）
UserContent = str | list[dict[str, Any]]


def _content_len(content: UserContent | Command) -> int:
    """日志用的"长度"：多模态时只统计文本块，别把 base64 算进去。"""
    if isinstance(content, Command):
        return 0
    if isinstance(content, str):
        return len(content)
    return sum(len(block["text"]) for block in content if block["type"] == "text")


def _build_subagents(
    tools: Sequence[BaseTool], business_subagents: Sequence[SubAgent], *, provider: str
) -> list[dict[str, Any]]:
    """合并内置与业务子 Agent，校验工具范围并补齐人工介入保护。

    返回新的配置，不修改原始声明；实际子 Agent 仍由 create_deep_agent 构建。
    """
    tools_by_name = {t.name: t for t in tools}
    subagents: list[dict[str, Any]] = []
    names: set[str] = set()
    for spec in (*BUILTIN_SUBAGENTS, *business_subagents):
        name = spec["name"]
        if name in names:
            raise ValueError(f"子 Agent 名称重复：{name}")
        names.add(name)
        # 省略 tools 才继承；显式 [] 不授予业务工具，不能用 `or tools` 扩大范围。
        selected = list(spec.get("tools", tools))
        for selected_tool in selected:
            tool_name = selected_tool.name
            if tool_name not in tools_by_name or tools_by_name[tool_name] is not selected_tool:
                raise ValueError(
                    f"子 Agent {name} 必须引用主 Agent 已注册的工具实例：{tool_name!r}"
                )
        subagents.append(
            {
                **spec,
                "tools": selected,
                "middleware": [
                    *spec.get("middleware", []),
                    ExecutionBudgetMiddleware(),
                    model_timeout_retry(provider),
                    ToolErrorMiddleware(),
                    HumanInteractionMiddleware(selected),
                ],
            }
        )

    # 默认通用代理也必须经过审批，不能只保护显式声明的子代理。
    if "general-purpose" not in names:
        subagents.append(
            {
                "name": "general-purpose",
                "description": "通用子任务执行者。由主 Agent 指定目标、材料、范围和验收要求，可协助研究、分析、写作、代码和文件处理，返回可核验的结果。",
                "system_prompt": GENERAL_WORKER_PROMPT,
                "middleware": [
                    ExecutionBudgetMiddleware(),
                    model_timeout_retry(provider),
                    ToolErrorMiddleware(),
                    HumanInteractionMiddleware(tools),
                ],
            }
        )
    return subagents


def build_core_agent(
    config: AppConfig,
    *,
    mcp_tools: Sequence[BaseTool] = (),
    checkpointer: Any | None = None,
) -> CompiledGraph[Any, MemoryContext, Any, Any]:
    """构造 AstraAgent 主智能体（LLM + 工具 + sub-agents + skills → 编译成图）。

    ``mcp_tools`` 与 ``checkpointer`` 都由 lifespan 先准备好再传进来：
    前者是异步资源，后者（Postgres 版）的初始化也是异步的，而本函数是同步的。
    不传则各自退回兜底实现（MCP 不接、checkpointer 用内存版）。
    """
    # 1) LLM
    # Agent 层统一重试超时；关闭 SDK 内部重试，防止三次重试被层层放大。
    llm = build_llm_client(config.llm.model_copy(update={"max_retries": 0}))

    # 2) 工具（RagWiki + business/ 下自动发现的全部业务）
    # 延迟导入：core/__init__ 会导入本模块，直接顶层导入 business 会形成循环
    from business import collect_subagents, collect_tools, discover_business

    business = discover_business()
    # 沙箱工具始终挂载：未配置时它自行返回「暂不可用」，不影响其他对话能力
    from core.report_tools import REPORT_TOOLS
    from core.sandbox.tools import SANDBOX_TOOLS

    # 报表渲染（render_spreadsheet / render_document）不依赖沙箱，始终可用
    tools: list[BaseTool] = [
        query_ragwiki,
        ask_user,
        *(getattr(sys_tools, name) for name in sys_tools.__all__),
        *collect_tools(business.bundles),
        *REPORT_TOOLS,
        *SANDBOX_TOOLS,
        *mcp_tools,
    ]

    # 3) 子 Agent
    subagents = _build_subagents(
        tools, collect_subagents(business.bundles), provider=config.llm.provider
    )

    # 4) Skills（文件型，加载到 system prompt）
    # SkillsMiddleware 会在首轮扫描目录；可选沙箱未启用时不要安装这个加载钩子。
    skill_paths = [SKILLS_ROOT + "/"] if sandbox_available() else None

    # 接了 MCP 才追加"外部工具信任边界"（防提示注入），没接就不提
    system_prompt = f"{SYSTEM_PROMPT}\n\n{MCP_NOTICE}" if mcp_tools else SYSTEM_PROMPT

    logger.info(
        "agent.build",
        tools=[t.name for t in tools],
        subagents=[s["name"] for s in subagents],
        skills=skill_paths,
        llm_model=config.llm.model,
        llm_provider=config.llm.provider,
    )

    # 5) deepagents 组合
    agent: CompiledGraph[Any, MemoryContext, Any, Any] = create_deep_agent(
        name="astra-agent",
        model=llm,
        tools=tools,
        subagents=subagents,
        skills=skill_paths,
        # 当前 deepagents 版本不再默认提供任务清单；显式挂载以随 checkpoint 保存进度。
        middleware=[
            TodoListMiddleware(),
            ExecutionBudgetMiddleware(),
            model_timeout_retry(config.llm.provider),
            ToolErrorMiddleware(),
            HumanInteractionMiddleware(tools),
        ],
        context_schema=MemoryContext,
        memory=["/memories/AGENTS.md", "/memories/habits.md"],
        checkpointer=get_checkpointer() if checkpointer is None else checkpointer,
        system_prompt=system_prompt,
        backend=get_backend(),
    )
    return agent.with_config({"recursion_limit": config.recursion_limit})


async def run_once(
    agent: CompiledGraph[Any, MemoryContext, Any, Any],
    user_input: UserContent | Command,
    thread_id: str,
    context: MemoryContext | None = None,
) -> dict[str, Any]:
    """单轮调用 agent（非流式，async），返回完整状态字典。

    **必须是 async**：配了 Postgres 时用的是 ``AsyncPostgresSaver``，
    而 LangGraph 的同步 ``invoke`` 不支持异步 checkpointer。
    ``context`` 不传则用默认匿名上下文 —— 业务工具会因缺权限拒绝写操作，
    这是有意的 fail-closed 设计。
    """
    ctx = context or MemoryContext(user_id="anonymous")
    assert_thread_owner(thread_id, ctx.user_id)
    ctx = ctx.model_copy(update={"extra": {**ctx.extra, "approval_thread_id": thread_id}})
    logger.info(
        "agent.invoke.start",
        input_len=_content_len(user_input),
        thread_id=thread_id,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        roles=sorted(ctx.roles),
    )
    run_id = uuid4()
    with operation(
        "agent.execute",
        thread_id=thread_id,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        run_id=str(run_id),
        **{"agent.resume": isinstance(user_input, Command)},
    ) as span:
        capture_io(
            span, "input", {"resume": True} if isinstance(user_input, Command) else user_input
        )
        result: dict[str, Any] = await agent.ainvoke(
            user_input
            if isinstance(user_input, Command)
            else {"messages": [{"role": "user", "content": user_input}]},
            config={
                "recursion_limit": (agent.config or {}).get("recursion_limit", 125),
                "configurable": {"thread_id": thread_id},
                "run_id": run_id,
            },
            context=ctx,
        )
        span.set_attribute(
            "agent.state", "suspended" if result.get("__interrupt__") else "completed"
        )
        if messages := result.get("messages"):
            capture_io(span, "output", messages[-1].content)
    logger.info("agent.invoke.done", user_id=ctx.user_id)
    return result


# ── 资源管理（Web 服务端必需）─────────────────────────────────


async def close_agent_resources() -> None:
    """释放全局资源：checkpointer / store / RagWiki 客户端 / 沙箱 / MCP / 业务子包。

    每项关闭都会执行；关闭错误由退出栈在清理完成后向调用方报告。
    """
    from business import collect_closers, discover_business
    from core.backend import close_store
    from core.checkpointer import close_checkpointer
    from core.sandbox.registry import shutdown_sandbox
    from ragwiki.client import close_ragwiki_client

    logger.info("agent.resources.closing")
    async with AsyncExitStack() as resources:
        # 后注册的资源先关闭；即使某个 closer 抛错，其余资源仍会释放。
        resources.callback(shutdown_sandbox)
        resources.push_async_callback(close_checkpointer)
        resources.callback(close_store)
        resources.push_async_callback(close_ragwiki_client)
        resources.push_async_callback(shutdown_mcp)
        for closer in collect_closers(discover_business().bundles):
            resources.push_async_callback(closer)

    logger.info("agent.resources.closed")


@asynccontextmanager
async def core_lifespan(
    config: AppConfig,
) -> AsyncIterator[CompiledGraph[Any, MemoryContext, Any, Any]]:
    """FastAPI / Starlette 风格的 lifespan 上下文管理器。"""
    # 沙箱在 agent 构建**之前**初始化：工具只是引用全局管理器，
    # 顺序反了也能工作，但先起沙箱能让启动日志尽早暴露配置问题。
    from core.checkpointer import init_checkpointer
    from core.mcp.registry import init_mcp
    from core.sandbox.registry import init_sandbox

    try:
        init_sandbox()
        # MCP 和 PG 自行隔离不可用能力；构图失败也必须释放已初始化的资源。
        checkpointer = await init_checkpointer()
        mcp_tools = await init_mcp()
        agent = build_core_agent(config, mcp_tools=mcp_tools, checkpointer=checkpointer)
        logger.info(
            "agent.lifespan.start",
            # 工具总清单在 agent.build 里已经打过（那里才是准的）
            mcp_tools=len(mcp_tools),
            checkpointer=type(checkpointer).__name__,
        )
        yield agent
    finally:
        await close_agent_resources()


async def stream_once(
    agent: CompiledGraph[Any, MemoryContext, Any, Any],
    user_input: UserContent | Command | None,
    thread_id: str,
    context: MemoryContext,
) -> Any:
    """逐条返回 LangGraph 事件；调用方负责准备完整的运行上下文。"""
    assert_thread_owner(thread_id, context.user_id)
    logger.info(
        "agent.stream.start",
        input_len=_content_len(user_input) if user_input is not None else 0,
        thread_id=thread_id,
        user_id=context.user_id,
        tenant_id=context.tenant_id,
        project_id=context.project_id,
        roles=sorted(context.roles),
    )
    run_id = uuid4()
    with operation(
        "agent.execute",
        thread_id=thread_id,
        user_id=context.user_id,
        tenant_id=context.tenant_id,
        project_id=context.project_id,
        run_id=str(run_id),
        **{"agent.resume": isinstance(user_input, Command)},
    ) as span:
        capture_io(
            span, "input", {"resume": True} if isinstance(user_input, Command) else user_input
        )
        span.set_attribute("agent.state", "running")
        suspended = False
        started = perf_counter()
        first_token = False
        try:
            async for event in agent.astream_events(
                user_input
                if user_input is None or isinstance(user_input, Command)
                else {"messages": [{"role": "user", "content": user_input}]},
                # astream_events 先补齐默认 config；必须显式传上限，避免 25 覆盖图配置。
                config={
                    "recursion_limit": (agent.config or {}).get("recursion_limit", 125),
                    "configurable": {"thread_id": thread_id},
                    "run_id": run_id,
                },
                context=context,
                version="v2",
            ):
                if event.get("event") == "on_chat_model_stream" and not first_token:
                    span.set_attribute(
                        "agent.first_token_ms", int((perf_counter() - started) * 1000)
                    )
                    first_token = True
                for key in ("output", "chunk"):
                    output = event.get("data", {}).get(key)
                    if isinstance(output, dict) and output.get("__interrupt__"):
                        suspended = True
                if event.get("event") == "on_chain_end" and not event.get("parent_ids"):
                    result = event.get("data", {}).get("output")
                    if isinstance(result, dict) and (messages := result.get("messages")):
                        capture_io(span, "output", messages[-1].content)
                yield event
        except BaseException as exc:
            span.set_attribute(
                "agent.state", "failed" if isinstance(exc, Exception) else "cancelled"
            )
            raise
        else:
            span.set_attribute("agent.state", "suspended" if suspended else "completed")
    logger.info("agent.stream.done", user_id=context.user_id)
