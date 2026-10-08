"""子任务展示记录独立保存，不把并发子模型内容拼入主回复。"""

import json
import time
from collections import defaultdict, deque

from langgraph.errors import GraphBubbleUp
from psycopg.types.json import Jsonb

from api.run_store import connect
from api.utils.messages import text_from_chunk, tool_result_failed, tool_result_text
from core.think import ThinkSplitter
from core.utils.logging import get_logger

logger = get_logger(__name__)


async def setup():
    async with await connect() as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS agent_subagent_runs (
            thread_id TEXT NOT NULL, run_id TEXT NOT NULL, call_id TEXT NOT NULL,
            payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(thread_id,run_id))""")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS subagent_call_idx ON agent_subagent_runs(thread_id,call_id)"
        )


async def load(thread_id, call_id):
    async with await connect() as db:
        row = await (
            await db.execute(
                """SELECT payload FROM agent_subagent_runs WHERE thread_id=%s AND
            (run_id=%s OR call_id=%s) ORDER BY updated_at DESC LIMIT 1""",
                (thread_id, call_id, call_id),
            )
        ).fetchone()
    return row["payload"] if row else None


async def delete(thread_id):
    async with await connect() as db:
        await db.execute("DELETE FROM agent_subagent_runs WHERE thread_id=%s", (thread_id,))


class SubagentRecorder:
    def __init__(self, thread_id):
        self.thread_id = thread_id
        self.tasks = {}
        self.messages = {}
        self.parsers = {}
        self.calls = defaultdict(deque)
        self.saved_at = {}

    @staticmethod
    def key(args):
        return json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)

    def append(self, task, message, channel, text):
        # 展示副本有界；完整模型上下文仍在框架检查点中，不改变执行输入。
        remaining = max(0, 1_000_000 - task["chars"])
        message[channel] = message.get(channel, "") + text[:remaining]
        task["chars"] += min(len(text), remaining)
        task["truncated"] |= len(text) > remaining

    async def observe(self, raw):
        kind, run = raw.get("event"), str(raw.get("run_id", ""))
        data = raw.get("data") or {}
        if kind == "on_chat_model_end":
            output = data.get("output")
            for call in getattr(output, "tool_calls", []) or []:
                if call.get("name") == "task":
                    self.calls[self.key(call.get("args", {}))].append(call["id"])
        if kind == "on_tool_start" and raw.get("name") == "task":
            args = data.get("input") or {}
            queue = self.calls[self.key(args)]
            self.tasks[run] = {
                "id": run,
                "call_id": queue.popleft() if queue else run,
                "description": str(args.get("description", "")) if isinstance(args, dict) else "",
                "agent": str(args.get("subagent_type", "general-purpose"))
                if isinstance(args, dict)
                else "general-purpose",
                "status": "running",
                "messages": [],
                "chars": 0,
                "truncated": False,
            }
            await self.save(run)
            return
        if run in self.tasks and kind in ("on_tool_end", "on_tool_error"):
            task = self.tasks[run]
            output = data.get("output")
            # task 返回 Command，里面的 ToolMessage 带原始调用 ID，用于刷新后定位。
            update = getattr(output, "update", None)
            if isinstance(update, dict):
                for message in update.get("messages", []):
                    if getattr(message, "tool_call_id", None):
                        task["call_id"] = message.tool_call_id
            task["status"] = (
                "waiting"
                if isinstance(data.get("error"), GraphBubbleUp)
                else "error"
                if kind == "on_tool_error" or tool_result_failed(output)
                else "completed"
            )
            await self.save(run)
            return
        parents = raw.get("parent_ids") or []
        owner = next(
            (str(parent) for parent in reversed(parents) if str(parent) in self.tasks), None
        )
        if owner is None:
            return
        task = self.tasks[owner]
        if kind in ("on_chat_model_start", "on_tool_start"):
            if len(task["messages"]) >= 5000:
                task["truncated"] = True
                return
            message = {
                "id": run,
                "kind": "model" if kind == "on_chat_model_start" else "tool",
                "name": raw.get("name", ""),
                "status": "running",
                "content": "",
                "reasoning": "",
            }
            self.messages[(owner, run)] = message
            task["messages"].append(message)
            if kind == "on_chat_model_start":
                self.parsers[run] = ThinkSplitter()
        message = self.messages.get((owner, run))
        if message is not None:
            if kind == "on_chat_model_stream":
                for channel, text in self.parsers[run].feed(text_from_chunk(data.get("chunk"))):
                    self.append(
                        task, message, "reasoning" if channel == "reasoning" else "content", text
                    )
            elif kind == "on_chat_model_end":
                for channel, text in self.parsers.pop(run, ThinkSplitter()).flush():
                    self.append(
                        task, message, "reasoning" if channel == "reasoning" else "content", text
                    )
                message["status"] = "completed"
            elif kind in ("on_tool_end", "on_tool_error"):
                message["status"] = (
                    "error"
                    if kind == "on_tool_error" or tool_result_failed(data.get("output"))
                    else "completed"
                )
                self.append(
                    task,
                    message,
                    "content",
                    tool_result_text(data.get("output"))
                    if kind == "on_tool_end"
                    else "工具执行失败",
                )
        if time.monotonic() - self.saved_at.get(owner, 0) >= 2:
            await self.save(owner)

    async def finish(self, status):
        for run, task in self.tasks.items():
            if task["status"] == "running":
                task["status"] = status
            for message in task["messages"]:
                parser = self.parsers.pop(message["id"], None)
                if parser:
                    for channel, text in parser.flush():
                        self.append(
                            task,
                            message,
                            "reasoning" if channel == "reasoning" else "content",
                            text,
                        )
            await self.save(run)

    async def save(self, run):
        self.saved_at[run] = time.monotonic()
        task = self.tasks[run]
        try:
            async with await connect() as db:
                await db.execute(
                    """INSERT INTO agent_subagent_runs(thread_id,run_id,call_id,payload)
                    VALUES(%s,%s,%s,%s) ON CONFLICT(thread_id,run_id) DO UPDATE SET
                    call_id=excluded.call_id,payload=excluded.payload,updated_at=now()""",
                    (self.thread_id, run, task["call_id"], Jsonb(task)),
                )
        except Exception:
            logger.exception("subagent.record.failed", thread_id=self.thread_id, run_id=run)
