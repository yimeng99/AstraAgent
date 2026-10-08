"""主智能体 CLI 入口。

注册到 :file:`pyproject.toml` 的 ``[project.scripts]``：

    astra-agent = "core.cli:main"

子命令：

* ``astra-agent``         —— 仅校验配置（不启动 agent）
* ``astra-agent chat``    —— 启动交互式 REPL
* ``astra-agent run "..."` —— 单轮执行
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

from api.utils.messages import text_from_chunk
from core.agent import build_core_agent, close_agent_resources, stream_once
from core.config import AppConfig, load_app_config
from core.context_type import MemoryContext
from core.exceptions import AstraAgentError, ConfigError
from core.sessions import new_thread_id
from core.utils.logging import configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from langgraph.graph.state import CompiledStateGraph as CompiledGraph

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astra-agent",
        description="AstraAgent — 集成 RagWiki 企业知识库的智能体。",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--log-format",
        default="console",
        choices=["console", "json"],
    )
    parser.add_argument(
        "--show-tools",
        action="store_true",
        help="显示工具 / 子 agent 调用过程（默认隐藏，避免泄露内部信息）。",
    )

    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("check", help="仅校验配置后退出。")
    sub.add_parser("chat", help="进入交互式对话。")

    p_run = sub.add_parser("run", help="单轮执行。")
    p_run.add_argument("prompt", help="用户输入。")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging(level=args.log_level, fmt=args.log_format)  # type: ignore[arg-type]

    # 1) 加载配置
    try:
        cfg = load_app_config()
    except ConfigError as exc:
        logger.error("config.load.failed", error=str(exc))
        print(f"配置加载失败：{exc}", file=sys.stderr)
        return 2

    # 2) 子命令处理
    cmd = args.cmd or "check"

    if cmd == "check":
        logger.info(
            "config.check.ok",
            llm_model=cfg.llm.model,
        )
        print(
            f"AstraAgent 配置 OK。\n"
            f"  LLM: {cfg.llm.provider}/{cfg.llm.model}\n"
            f"  Workspace: {cfg.workspace.root.as_posix()}"
        )
        return 0

    # chat / run 都要建 agent —— 但**必须在 asyncio.run 内部**建：
    # 配了 Postgres 时 checkpointer 是异步的，连接池绑定创建它的 loop。
    if cmd == "chat":
        return _repl(cfg, show_tools=args.show_tools)
    if cmd == "run":
        return _run(cfg, args.prompt, show_tools=args.show_tools)

    parser.print_help()
    return 1


async def _build_agent(cfg: AppConfig) -> CompiledGraph:
    """在当前事件循环里初始化 checkpointer，再构造 agent（见上面注释）。"""
    from core.checkpointer import init_checkpointer

    checkpointer = await init_checkpointer()
    return build_core_agent(cfg, checkpointer=checkpointer)


async def _render_stream(
    events: AsyncIterator[dict],
    *,
    show_tool_calls: bool = False,
    thread_id: str | None = None,
) -> None:
    """把 ``astream_events`` 事件渲染到 stdout。

    默认**只渲染 AI 文本**，不暴露工具 / 子 agent 的中间调用。
    设 ``show_tool_calls=True``（或 CLI 加 ``--show-tools``）可打开调试视图。

    流结束后若同一线程产生了产物（报表/文档），打印一行 ``[artifact] filename (size)``，
    让 CLI 用户至少知道文件**确实落了库**（CLI 没法预览，但 web 端有产物卡片）。

    隐藏 tool trace 的原因：
    * 工具名 / 输入 / 输出可能包含敏感信息（路径、token、参数）
    * 用户只需看最终 AI 回复，不需要过程
    """
    printed_any = False
    async for event in events:
        kind = event.get("event", "")
        data = event.get("data", {}) or {}

        if kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            if chunk is None:
                continue
            content = text_from_chunk(chunk)
            if content:
                _safe_print(content, end="", flush=True)
                printed_any = True

        elif kind == "on_tool_start" and show_tool_calls:
            name = event.get("name", "?")
            inp = data.get("input", "")
            _safe_print(f"\n[tool:start] {name}({_truncate(str(inp), 80)})", flush=True)
            printed_any = True

        elif kind == "on_tool_end" and show_tool_calls:
            name = event.get("name", "?")
            out = data.get("output", "")
            _safe_print(f"[tool:end]   {name} → {_truncate(str(out), 80)}", flush=True)

    if printed_any:
        print()  # 末尾换行

    if thread_id is not None:
        # 把本轮产物告诉 CLI 用户（web 端有产物卡片，CLI 只能列文件）
        try:
            from core.artifacts import take_pending

            for artifact in take_pending(thread_id):
                # Artifact 是 dataclass；asdict 是它的标准序列化方式
                from dataclasses import asdict

                payload = asdict(artifact)
                _safe_print(
                    f"[artifact] {payload.get('filename', '?')} "
                    f"({_truncate(str(payload.get('size', 0)) + ' bytes', 16)}, "
                    f"file_id={payload.get('file_id', '?')})",
                    flush=True,
                )
        except Exception:  # pragma: no cover - 产物不应当拖崩 CLI
            logger.exception("cli.render_artifacts.failed")


def _truncate(s: str, maxlen: int) -> str:
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def _safe_print(s: str, *, end: str = "\n", flush: bool = False) -> None:
    """对控制台安全地输出（emoji / GBK 字符不会让 print 抛错）。

    优先走 ``sys.stdout.buffer`` + ``sys.stdout.encoding``（Windows 上是 cp936 / utf-8），
    buffer 写失败（被重定向、管道编码不接受）时再降级为 ASCII replace。
    """
    enc = sys.stdout.encoding or "utf-8"
    try:
        sys.stdout.buffer.write(s.encode(enc, errors="replace"))
        if end:
            sys.stdout.buffer.write(end.encode(enc))
        if flush:
            sys.stdout.buffer.flush()
        return
    except (AttributeError, UnicodeEncodeError):
        pass
    # 降级：buffer 不可用或编码错误（如 cp65001 utf-8 在某些管道里拒绝 emoji） → ASCII
    import contextlib

    try:
        sys.stdout.write(s.encode("ascii", errors="replace").decode("ascii"))
        if end:
            sys.stdout.write(end)
        if flush:
            with contextlib.suppress(Exception):
                sys.stdout.flush()
    except Exception:  # pragma: no cover - 最后兜底：什么都不打
        pass


async def _run_async(cfg: AppConfig, prompt: str, *, show_tools: bool = False) -> int:
    """单轮执行（流式输出）。"""
    try:
        agent = await _build_agent(cfg)
    except AstraAgentError as exc:
        logger.error("agent.build.failed", error=str(exc))
        print(f"构造 agent 失败：{exc}", file=sys.stderr)
        return 3

    thread_id = new_thread_id("anonymous")
    context = MemoryContext(user_id="anonymous", extra={"approval_thread_id": thread_id})
    try:
        events = stream_once(agent, prompt, thread_id=thread_id, context=context)
        await _render_stream(events, show_tool_calls=show_tools, thread_id=thread_id)
    except AstraAgentError as exc:
        logger.error("agent.run.failed", error=str(exc))
        print(f"\n执行失败：{exc}", file=sys.stderr)
        return 4
    finally:
        await close_agent_resources()
    return 0


async def _repl_async(cfg: AppConfig, *, show_tools: bool = False) -> int:
    """交互式 REPL（流式）。"""
    print("AstraAgent REPL（输入空行或 Ctrl+C 退出）")
    try:
        agent = await _build_agent(cfg)
    except AstraAgentError as exc:
        logger.error("agent.build.failed", error=str(exc))
        print(f"构造 agent 失败：{exc}", file=sys.stderr)
        return 3

    thread_id = new_thread_id("anonymous")
    context = MemoryContext(user_id="anonymous", extra={"approval_thread_id": thread_id})
    try:
        while True:
            try:
                line = await asyncio.to_thread(input, "> ")
            except EOFError:
                return 0
            line = line.strip()
            if not line:
                return 0
            try:
                events = stream_once(agent, line, thread_id=thread_id, context=context)
                await _render_stream(events, show_tool_calls=show_tools, thread_id=thread_id)
            except AstraAgentError as exc:
                logger.error("agent.repl.failed", error=str(exc))
                print(f"\n执行失败：{exc}", file=sys.stderr)
            print()
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        await close_agent_resources()


def _run(cfg: AppConfig, prompt: str, *, show_tools: bool = False) -> int:
    """同步 wrapper：兼容 argparse 调用。"""
    return asyncio.run(_run_async(cfg, prompt, show_tools=show_tools))


def _repl(cfg: AppConfig, *, show_tools: bool = False) -> int:
    """同步 wrapper。"""
    return asyncio.run(_repl_async(cfg, show_tools=show_tools))


if __name__ == "__main__":
    raise SystemExit(main())
