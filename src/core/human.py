"""在执行工具前保存人工交互断点，不占用协程等待用户。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import PrivateStateAttr
from langchain.tools import tool
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command, interrupt
from pydantic import Field

from core.config import PROJECT_ROOT
from core.context_type import MemoryContext
from core.sessions import ThreadAccessError, assert_thread_owner

READ_TOOLS = frozenset({"query_ragwiki", "ls", "read_file", "glob", "grep"})
CONTROL_TOOLS = frozenset({"task", "write_todos"})


def fingerprint(args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def display_args(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[已隐藏敏感值]"
            if any(
                part in key.lower()
                for part in ("password", "secret", "token", "api_key", "authorization")
            )
            else display_args(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [display_args(item) for item in value]
    return value


def _session_write(name: str, args: dict | None, ctx: Any) -> bool:
    if name not in {"write_file", "edit_file"} or not isinstance(ctx, MemoryContext):
        return False
    if ctx.user_id == "anonymous" or not ctx.can("read"):
        return False
    path = (args or {}).get("file_path")
    if not isinstance(path, str) or not path.strip():
        return False
    # CompositeBackend 的长期记忆路由不能随会话工作区一起免审批。
    from pathlib import PurePosixPath

    from core.sandbox.sessions import resolve_path, session_root

    normalized = str(PurePosixPath("/" + path.lstrip("/")))
    if normalized == "/memories" or normalized.startswith("/memories/"):
        return False
    if normalized == "/workspace/skills" or normalized.startswith("/workspace/skills/"):
        return False
    thread = str(ctx.extra.get("approval_thread_id", ""))
    try:
        assert_thread_owner(thread, ctx.user_id)
        resolve_path(session_root(thread), path)
    except (ValueError, PermissionError, ThreadAccessError):
        return False
    # 实际读写仍由沙箱后端检查路径、符号链接和会话隔离。
    return True


def needs_approval(name: str, tool: Any, args: dict | None = None, ctx: Any = None) -> bool:
    # 提问由 after_model 收集，不能因 read_only 元数据绕过回答校验。
    if name == "ask_user":
        return True
    if _session_write(name, args, ctx):
        return False
    metadata = getattr(tool, "metadata", None) or {}
    return not (
        name in READ_TOOLS | CONTROL_TOOLS
        or (not name.startswith("mcp__") and metadata.get("approval_mode") == "read_only")
        or (name == "run_python" and metadata.get("approval_mode") == "sandbox_execution")
    )


@tool
async def ask_user(
    question: Annotated[str, Field(min_length=1, max_length=500)],
    options: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=120)]], Field(max_length=4)
    ]
    | None = None,
) -> str:
    """缺少关键需求时向用户提一个简明问题，展示输入框并挂起任务。

    可提供最多四个清晰、互斥的建议选项，始终允许自由输入。
    问题说明用户需要做出的选择，不暴露工具名或参数；不要用于写操作审批。
    """
    # 正常路径由中间件写入用户回答；误配置时不能伪造回答或继续任务。
    raise RuntimeError("未启用持久化人工交互中间件")


def merge_human_decisions(current: dict, incoming: dict) -> dict:
    # 兼容旧检查点里已经回传的并行子任务更新；审批仍校验消息、身份及参数摘要。
    return {**current, **incoming}


class HumanState(AgentState):
    # 审批只属于当前 agent，不应传给子任务或随着子任务结果回流父图。
    human_decisions: NotRequired[Annotated[dict, PrivateStateAttr, merge_human_decisions]]


class HumanInteractionMiddleware(AgentMiddleware):
    state_schema = HumanState

    def __init__(self, tools):
        self.tools_by_name = {tool.name: tool for tool in tools}

    async def aafter_model(self, state, runtime):
        last = next(
            (msg for msg in reversed(state["messages"]) if isinstance(msg, AIMessage)), None
        )
        if not last or not last.tool_calls:
            return None
        ctx = runtime.context
        if not isinstance(ctx, MemoryContext):
            raise ValueError("缺少人工交互上下文")
        thread = str(ctx.extra.get("approval_thread_id", ""))
        assert_thread_owner(thread, ctx.user_id)
        items = []
        for call in last.tool_calls:
            name = call["name"]
            if name == "ask_user":
                args = call["args"]
                question = args.get("question", "")
                options = args.get("options") or []
                if not isinstance(question, str) or not question.strip() or len(question) > 500:
                    raise ValueError("问题内容不合法")
                # 模型可能忽略工具 schema；建议选项不应让用户回答入口一起失效。
                # 不截断选项文字，以免改变含义；无法展示的选项退回自由输入。
                options = (
                    list(
                        dict.fromkeys(
                            option.strip()
                            for option in options
                            if isinstance(option, str)
                            and option.strip()
                            and len(option.strip()) <= 120
                        )
                    )[:4]
                    if isinstance(options, list)
                    else []
                )
                item = {"kind": "question", "question": question, "options": options}
            elif not needs_approval(name, self.tools_by_name.get(name), call["args"], ctx):
                continue
            else:
                item = {"kind": "approval", "tool": name, "args": display_args(call["args"])}
            items.append({**item, "call_id": call["id"], "digest": fingerprint(call["args"])})
        if not items:
            return {"human_decisions": {}}
        # 在工具执行前一并挂起，恢复节点不会重复执行此前的写操作。
        response = interrupt(
            {
                "kind": "human",
                "thread_id": thread,
                "user_id": ctx.user_id,
                "org_id": ctx.tenant_id,
                "project_id": ctx.project_id,
                "items": items,
            }
        )
        if not isinstance(response, dict) or set(response) != {item["call_id"] for item in items}:
            raise ValueError("人工交互响应与挂起操作不一致")
        results = []
        approved = {}
        for item in items:
            decision = response[item["call_id"]]
            if not isinstance(decision, dict) or decision.get("digest") != item["digest"]:
                raise ValueError("操作参数已改变，不能复用确认")
            if item["kind"] == "question":
                answer = decision.get("answer", "")
                if not isinstance(answer, str) or not answer.strip() or len(answer) > 4000:
                    raise ValueError("回答内容不合法")
                results.append(
                    ToolMessage(
                        tool_call_id=item["call_id"],
                        name="ask_user",
                        content=json.dumps(
                            {"question": item["question"], "answer": answer}, ensure_ascii=False
                        ),
                    )
                )
            elif decision.get("approve") is False:
                results.append(
                    ToolMessage(
                        tool_call_id=item["call_id"],
                        name=item["tool"],
                        content="用户拒绝了本次操作，未执行；不要重试，除非用户再次明确要求。",
                        status="error",
                    )
                )
            elif decision.get("approve") is not True:
                raise ValueError("审批结果不合法")
            else:
                approved[item["call_id"]] = {
                    "digest": item["digest"],
                    "message_id": last.id,
                    "user_id": ctx.user_id,
                    "org_id": ctx.tenant_id,
                    "project_id": ctx.project_id,
                    "thread_id": thread,
                }
        return {"messages": results, "human_decisions": approved}

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        name = call["name"]
        if not needs_approval(name, request.tool, call["args"], request.runtime.context):
            return await handler(request)
        # 旧版本 checkpoint 或直接从 tools 节点恢复也不能绕过审批。
        ctx = request.runtime.context
        last = next(
            (msg for msg in reversed(request.state["messages"]) if isinstance(msg, AIMessage)), None
        )
        accepted = request.state.get("human_decisions", {}).get(call["id"])
        expected = (
            {
                "digest": fingerprint(call["args"]),
                "message_id": last.id if last else None,
                "user_id": ctx.user_id,
                "org_id": ctx.tenant_id,
                "project_id": ctx.project_id,
                "thread_id": str(ctx.extra.get("approval_thread_id", "")),
            }
            if isinstance(ctx, MemoryContext)
            else None
        )
        if not accepted or accepted != expected:
            return ToolMessage(
                tool_call_id=call["id"],
                status="error",
                content="本次操作没有有效确认，未执行。请重新发起请求并确认。",
            )
        return await handler(request)


class HumanInputError(ValueError):
    """回答类型或内容不符合当前挂起事项。"""


class HumanConflictError(ValueError):
    """事项已处理或不存在，客户端应重新读取待办。"""


_locks: dict[str, asyncio.Lock] = {}


def thread_lock(thread: str) -> asyncio.Lock:
    # 同一进程的普通调用、流式调用和恢复共享锁；不替代多进程分布式锁。
    return _locks.setdefault(thread, asyncio.Lock())


@contextmanager
def decision_connection():
    # 沿用已有表和键，使部署前已回答一部分的任务仍可恢复。
    path = PROJECT_ROOT / "workspace" / "human-decisions.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS decisions (
            scope TEXT, thread TEXT, interrupt TEXT, call TEXT, response TEXT,
            PRIMARY KEY(scope, thread, interrupt, call))""")
        yield db


def _scope(ctx: MemoryContext) -> str:
    # 无项目时沿用旧审批存储键；checkpoint 的 org_id 键同样保留兼容。
    parts = [ctx.tenant_id, ctx.user_id]
    return json.dumps([*parts, ctx.project_id] if ctx.project_id else parts)


async def _batches(agent, ctx: MemoryContext, thread: str):
    assert_thread_owner(thread, ctx.user_id)
    state = await agent.aget_state({"configurable": {"thread_id": thread}})
    result = []
    for item in state.interrupts:
        value = item.value
        if not isinstance(value, dict) or value.get("kind") != "human":
            continue
        if (
            value.get("thread_id"),
            value.get("user_id"),
            value.get("org_id"),
            value.get("project_id", ""),
        ) != (
            thread,
            ctx.user_id,
            ctx.tenant_id,
            ctx.project_id,
        ):
            raise ThreadAccessError("对话不存在")
        result.append((item.id, value["items"]))
    return result


def _responses(ctx: MemoryContext, thread: str, interrupt_id: str) -> dict:
    with decision_connection() as db:
        rows = db.execute(
            "SELECT call, response FROM decisions WHERE scope=? AND thread=? AND interrupt=?",
            (_scope(ctx), thread, interrupt_id),
        ).fetchall()
    return {call: json.loads(response) for call, response in rows}


async def pending(agent, ctx: MemoryContext, thread: str) -> dict:
    approvals, questions = [], []
    for interrupt_id, items in await _batches(agent, ctx, thread):
        saved = _responses(ctx, thread, interrupt_id)
        ready = all(item["call_id"] in saved for item in items)
        # 回答落库后若请求中断，保留一个入口让用户继续触发恢复。
        for index, item in enumerate(items):
            if (ready and index != 0) or (not ready and item["call_id"] in saved):
                continue
            public = {
                **item,
                "id": f"{interrupt_id}:{index}",
                "thread_id": thread,
                "status": "pending",
                "expires_at": None,
                "resume_ready": ready,
            }
            (questions if item["kind"] == "question" else approvals).append(public)
    return {"approvals": approvals, "questions": questions}


async def prepare_resume(
    agent,
    ctx: MemoryContext,
    thread: str,
    item_id: str,
    approve: bool | None = None,
    answer: str | None = None,
) -> Command | None:
    # 调用方须持有 thread_lock，直到图完成或再次挂起。
    for interrupt_id, items in await _batches(agent, ctx, thread):
        for index, item in enumerate(items):
            if item_id != f"{interrupt_id}:{index}":
                continue
            saved = _responses(ctx, thread, interrupt_id)
            if all(entry["call_id"] in saved for entry in items):
                return Command(resume={interrupt_id: saved})
            if item["call_id"] in saved:
                raise HumanConflictError("此项已处理，请处理剩余事项")
            if item["kind"] == "approval":
                if not isinstance(approve, bool) or answer is not None:
                    raise HumanInputError("请确认或拒绝本次操作")
                response = {"approve": approve, "digest": item["digest"]}
            else:
                if (
                    not isinstance(answer, str)
                    or not answer.strip()
                    or len(answer) > 4000
                    or approve is not None
                ):
                    raise HumanInputError("请输入 1 到 4000 字的回答")
                response = {"answer": answer.strip(), "digest": item["digest"]}
            with decision_connection() as db:
                try:
                    db.execute(
                        "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
                        (_scope(ctx), thread, interrupt_id, item["call_id"], json.dumps(response)),
                    )
                except sqlite3.IntegrityError:
                    raise HumanConflictError("此项已处理") from None
            saved[item["call_id"]] = response
            return (
                Command(resume={interrupt_id: saved})
                if all(entry["call_id"] in saved for entry in items)
                else None
            )
    raise HumanConflictError("挂起事项已处理或不存在，请刷新会话")


async def prepare_approval_batch(
    agent, ctx: MemoryContext, thread: str, ids: list[str], approve: bool
):
    """只处理客户端已展示的事项；一次事务保存，再统一恢复并行断点。"""
    if not ids or len(ids) != len(set(ids)) or not isinstance(approve, bool):
        raise HumanInputError("审批列表或结果不合法")
    batches = await _batches(agent, ctx, thread)
    entries = {
        f"{interrupt_id}:{index}": (interrupt_id, item)
        for interrupt_id, items in batches
        for index, item in enumerate(items)
    }
    if any(item_id not in entries for item_id in ids):
        raise HumanConflictError("待审批事项已变化，请刷新后重试")
    if any(entries[item_id][1]["kind"] != "approval" for item_id in ids):
        raise HumanInputError("提问需要单独回答，不能批量审批")
    with decision_connection() as db:
        for item_id in ids:
            interrupt_id, item = entries[item_id]
            # 重复提交沿用原决定，绝不将已拒绝的操作改成批准。
            db.execute(
                "INSERT OR IGNORE INTO decisions VALUES (?, ?, ?, ?, ?)",
                (
                    _scope(ctx),
                    thread,
                    interrupt_id,
                    item["call_id"],
                    json.dumps({"approve": approve, "digest": item["digest"]}),
                ),
            )
    ready = {}
    for interrupt_id, items in batches:
        saved = _responses(ctx, thread, interrupt_id)
        if all(item["call_id"] in saved for item in items):
            ready[interrupt_id] = saved
    return Command(resume=ready) if ready else None
