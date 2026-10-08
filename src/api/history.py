"""从 agent 的 LangGraph 状态里读取对话历史。

为什么不用 ``checkpointer.aget_tuple`` 直接读：LangGraph 2.x 对大状态启用了
**delta 快照**，``aget_tuple`` 返回的 ``channel_values`` 只含未被 delta 化的通道
（实测 deepagents 跑一轮后 ``messages`` 有版本号却不在字典里），必须按 checkpoint
链逐个合并才能还原。``CompiledStateGraph.aget_state()`` 内部已完成合并，故统一走它。

（``alist`` 仍直接用 checkpointer —— 那只需要 thread_id，delta 不影响。）
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from api.run_failures import failure_threads, load_failures
from api.utils.messages import text_of, tool_result_failed, tool_result_text
from core.artifacts import load_thread_artifacts
from core.sessions import owned_by_thread_id
from core.think import ThinkSplitter
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph

logger = get_logger(__name__)

__all__ = [
    "ATTACHMENT_CONTEXT_MARKER",
    "HistoryMessage",
    "ThreadSummary",
    "list_history_threads",
    "load_thread_messages",
    "make_title",
    "owned_by_thread_id",
    "split_attachment_context",
    "split_reasoning",
]


def split_reasoning(content: str) -> tuple[str, str]:
    """把历史消息里的 ``<think>…</think>`` 段拆出来，返回 ``(正文, 思维链)``。

    为什么在这里拆：模型把思维链写在 ``content`` 里，而这条原始文本**必须原样
    回传给模型**（MiniMax 多轮工具调用靠它续思维链）。于是"存储保留、展示拆分" ——
    推送流时按增量拆、读历史时按整段拆，两边用同一个切分器，保证刷新前后一致。
    """
    splitter = ThinkSplitter()
    text = ""
    reasoning = ""
    for kind, piece in (*splitter.feed(content), *splitter.flush()):
        if kind == "reasoning":
            reasoning += piece
        else:
            text += piece
    return text, reasoning


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    """从 checkpoint 还原出的一条消息。"""

    id: str
    role: str
    content: str
    #: 思维链（``<think>`` 段）。存储里是原样保留的，读给前端时才拆开
    reasoning: str = ""
    #: 用户消息携带的附件（从注入清单里解析回来的，见 split_attachment_context）
    attachments: tuple[dict[str, Any], ...] = ()
    #: 助手在这一轮产出的文件（报表/文档），来自 core.artifacts 的线程日志
    artifacts: tuple[dict[str, Any], ...] = ()
    #: 从 AIMessage.tool_calls 与后续 ToolMessage 还原，用于刷新后回显工具结果。
    tools: tuple[dict[str, str], ...] = ()
    failure: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ThreadSummary:
    """一个对话的摘要（侧边栏列表项）。"""

    id: str
    title: str
    message_count: int
    updated_at: str


def _config_for(thread_id: str) -> RunnableConfig:
    """构造查询某个 thread 的 config。"""
    return {"configurable": {"thread_id": thread_id}}


async def load_thread_messages(
    agent: CompiledStateGraph[Any, Any, Any, Any], thread_id: str
) -> list[HistoryMessage]:
    """读取某个对话的完整消息历史（按时间正序；thread 不存在时返回空列表）。

    走 ``aget_state`` 而非 checkpointer —— 前者会自动合并 delta 快照（见模块 docstring）。
    """
    try:
        snapshot = await agent.aget_state(_config_for(thread_id))
    except Exception:
        logger.exception("history.load.failed", thread_id=thread_id)
        snapshot = None

    raw_messages = (getattr(snapshot, "values", None) or {}).get("messages") or []
    messages = [_to_history_message(m) for m in raw_messages]
    call_positions: dict[str, tuple[int, int]] = {}
    for index, raw in enumerate(raw_messages):
        if messages[index].role == "assistant":
            calls = (
                raw.get("tool_calls", [])
                if isinstance(raw, dict)
                else getattr(raw, "tool_calls", [])
            )
            tools: list[dict[str, str]] = []
            for call in calls or []:
                if not isinstance(call, dict) or not call.get("id") or not call.get("name"):
                    continue
                call_positions[str(call["id"])] = (index, len(tools))
                tools.append(
                    {
                        "id": str(call["id"]),
                        "name": str(call["name"]),
                        "status": "running",
                        "result": "",
                    }
                )
            messages[index] = replace(messages[index], tools=tuple(tools))
        elif messages[index].role == "tool":
            call_id = (
                raw.get("tool_call_id")
                if isinstance(raw, dict)
                else getattr(raw, "tool_call_id", None)
            )
            position = call_positions.get(str(call_id))
            if position is None:
                continue
            assistant_index, tool_index = position
            tools = list(messages[assistant_index].tools)
            tool = dict(tools[tool_index])
            tool["status"] = "error" if tool_result_failed(raw, tool["name"]) else "success"
            tool["result"] = tool_result_text(raw)
            tools[tool_index] = tool
            messages[assistant_index] = replace(messages[assistant_index], tools=tuple(tools))
    messages = _attach_artifacts(messages, thread_id)
    if any(tool["status"] == "running" for message in messages for tool in message.tools):
        from api.run_store import status as run_status

        waiting = any(task.interrupts for task in getattr(snapshot, "tasks", ()))
        if not waiting and await run_status(thread_id) != "running":
            messages = [
                replace(
                    message,
                    tools=tuple(
                        {
                            **tool,
                            "status": "interrupted",
                            "result": "执行中断，未确认工具结果。恢复前请核对已生成的文件。",
                        }
                        if tool["status"] == "running"
                        else tool
                        for tool in message.tools
                    ),
                )
                for message in messages
            ]
    failures = await asyncio.to_thread(load_failures, thread_id)
    positions = {m.id: index + 1 for index, m in enumerate(messages) if m.id}
    inserts: dict[int, list[HistoryMessage]] = {}
    for record in failures:
        position = positions.get(record["after_id"], min(record["after_count"], len(messages)))
        # 未收到结果只代表执行中断，不能声称工具已失败或已完成。
        for index in range(position):
            tools = tuple(
                {**tool, "status": "interrupted", "result": "任务中断，未收到工具完成结果。"}
                if tool["status"] == "running"
                else tool
                for tool in messages[index].tools
            )
            messages[index] = replace(messages[index], tools=tools)
        inserts.setdefault(position, []).append(
            HistoryMessage(
                id=record["failure"]["id"],
                role="assistant",
                content=record["content"],
                reasoning=record["reasoning"],
                failure=record["failure"],
            )
        )
    result = list(inserts.get(0, []))
    for index, message in enumerate(messages, start=1):
        result.append(message)
        result.extend(inserts.get(index, []))
    return result


def _attach_artifacts(messages: list[HistoryMessage], thread_id: str) -> list[HistoryMessage]:
    """把该会话累积的产物挂到最后一条 assistant 消息上。

    产物由工具生成时写进了 ``core.artifacts`` 的线程日志（checkpointer 里只有
    工具返回的文本）。不挂回去的话，刷新页面后文件还在存储里，但聊天记录里
    没有下载入口 —— 用户等于拿不到。
    """
    artifacts = load_thread_artifacts(thread_id)
    if not artifacts:
        return messages

    payload = tuple(a.to_dict() for a in artifacts)
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "assistant":
            messages[index] = replace(messages[index], artifacts=payload)
            break
    return messages


#: 「用户原话」与「附件上下文」的分隔标记（由 :mod:`api.routes.chat` 注入）。
#:
#: 模型需要看到附件正文，但**不能把注入的内容当成用户说过的话**：否则历史
#: 回显会糊一大段文档正文，连对话标题都会被污染。所以注入时打标记，回显时
#: 在标记处截断，并把它后面的附件清单解析回结构化数据。
ATTACHMENT_CONTEXT_MARKER: str = "\n\n<<<附件内容>>>\n"


def split_attachment_context(text: str) -> tuple[str, list[dict[str, Any]]]:
    """把消息拆成 ``(用户原话, 附件清单)``。

    注入格式（见 :func:`api.attachments.build_user_content`）::

        <用户原话>
        <<<附件内容>>>
        {"attachments": [...]}      ← 一行 JSON，供回显还原文件卡片
        ...给模型看的正文/说明...

    没有标记时原样返回文本与空列表。
    """
    index = text.find(ATTACHMENT_CONTEXT_MARKER)
    if index == -1:
        return text.strip(), []

    user_text = text[:index].strip()
    rest = text[index + len(ATTACHMENT_CONTEXT_MARKER) :]

    attachments: list[dict[str, Any]] = []
    first_line, _, _ = rest.partition("\n")
    try:
        payload = json.loads(first_line)
        if isinstance(payload, dict) and isinstance(payload.get("attachments"), list):
            attachments = [item for item in payload["attachments"] if isinstance(item, dict)]
    except ValueError:
        # 老消息没有清单行：正文照样截断，只是文件卡片还原不出来
        logger.debug("history.attachment_manifest.missing")

    return user_text, attachments


def _to_history_message(m: object) -> HistoryMessage:
    """把一条 LangChain 消息转成 :class:`HistoryMessage`。"""
    if isinstance(m, dict):
        mid = str(m.get("id") or "")
        role = str(m.get("role") or m.get("type") or "assistant")
        content = m.get("content", "")
    else:
        mid = str(getattr(m, "id", "") or "")
        mtype = str(getattr(m, "type", "") or "assistant")
        role = {"human": "user", "ai": "assistant"}.get(mtype, mtype)
        content = getattr(m, "content", "")

    # role 归一化到前端认识的几种
    if role in ("HumanMessage", "human"):
        role = "user"
    elif role in ("AIMessage", "ai"):
        role = "assistant"

    text = text_of(content)
    reasoning = ""
    attachments: list[dict[str, Any]] = []

    if role == "assistant":
        # 只有 assistant 的正文里会有思维链；用户手打的 <think> 原样保留
        text, reasoning = split_reasoning(text)
    else:
        # 用户消息：剥掉"给模型看的附件正文"，只留用户真正说的话
        text, attachments = split_attachment_context(text)

    return HistoryMessage(
        id=mid,
        role=role,
        content=text,
        reasoning=reasoning,
        attachments=tuple(attachments),
    )


def make_title(messages: Sequence[HistoryMessage], fallback: str) -> str:
    """用第一条用户消息当标题。"""
    for m in messages:
        if m.role == "user" and m.content.strip():
            text = m.content.strip().replace("\n", " ")
            return text[:30] + ("…" if len(text) > 30 else "") or fallback
    for m in messages:
        if m.failure and m.failure.get("input"):
            text = m.failure["input"].strip().replace("\n", " ")
            return text[:30] + ("…" if len(text) > 30 else "") or fallback
    return fallback


async def list_history_threads(
    agent: CompiledStateGraph[Any, Any, Any, Any],
    *,
    limit: int = 50,
    user_id: str | None = None,
) -> list[ThreadSummary]:
    """枚举所有对话，按最近更新倒序（`user_id` 给出时只返回归属该用户的）。

    先读取每个主会话的最新检查点元数据，避免全量反序列化历史状态；
    标题与消息数再逐个走 :func:`load_thread_messages` 补齐。
    """
    from core.checkpointer import list_checkpoint_threads

    # 只枚举主会话，子智能体的 checkpoint namespace 不参与会话排序。
    seen: dict[str, str] = {}
    try:
        seen = await list_checkpoint_threads(user_id, limit)
    except Exception:
        logger.exception("history.list.failed")

    # 输入准备或检查点故障也可能发生在首条消息落库之前。
    if user_id is not None:
        for thread_id, timestamp in (
            await asyncio.to_thread(failure_threads, user_id, limit)
        ).items():
            seen[thread_id] = max(seen.get(thread_id, ""), timestamp)
    seen = dict(sorted(seen.items(), key=lambda item: item[1], reverse=True)[:limit])

    # 补齐标题与消息数（逐个读最新状态）
    summaries: list[ThreadSummary] = []
    for thread_id, ts in seen.items():
        messages = await load_thread_messages(agent, thread_id)
        summaries.append(
            ThreadSummary(
                id=thread_id,
                title=make_title(messages, thread_id),
                message_count=len(messages),
                updated_at=ts,
            )
        )
    return summaries
