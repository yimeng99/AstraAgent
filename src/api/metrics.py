"""按实际模型调用采集统计；统计失败不影响对话，PG 保存累计快照供刷新恢复。"""

import time
from uuid import uuid4

from psycopg.types.json import Jsonb

from api.run_store import connect
from core.utils.logging import get_logger

logger = get_logger(__name__)
FIELDS = (
    "model_calls",
    "tool_calls",
    "steps",
    "model_seconds",
    "tool_seconds",
    "input_tokens",
    "output_tokens",
    "usage_calls",
    "ttft_seconds",
    "ttft_calls",
    "generation_seconds",
    "speed_tokens",
    "cache_read_tokens",
    "cache_input_tokens",
)


def combine(*values):
    result = {key: sum(value.get(key, 0) for value in values) for key in FIELDS}
    result["ttft"] = result["ttft_seconds"] / result["ttft_calls"] if result["ttft_calls"] else None
    result["tps"] = (
        result["speed_tokens"] / result["generation_seconds"]
        if result["generation_seconds"]
        else None
    )
    result["cache_hit_rate"] = (
        result["cache_read_tokens"] / result["cache_input_tokens"]
        if result["cache_input_tokens"]
        else None
    )
    result["total_tokens"] = (
        result["input_tokens"] + result["output_tokens"] if result["usage_calls"] else None
    )
    result["context_percent"] = None  # 未配置可信的模型上下文上限，不能由累计 token 推算。
    return result


async def setup():
    async with await connect() as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS agent_metrics (
            thread_id TEXT NOT NULL, run_id TEXT NOT NULL, payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(thread_id, run_id))""")


async def load(thread_id):
    async with await connect() as db:
        rows = await (
            await db.execute("SELECT payload FROM agent_metrics WHERE thread_id=%s", (thread_id,))
        ).fetchall()
    return combine(*(row["payload"] for row in rows))


async def delete(thread_id):
    async with await connect() as db:
        await db.execute("DELETE FROM agent_metrics WHERE thread_id=%s", (thread_id,))


class Collector:
    def __init__(self, thread_id, clock=time.monotonic):
        self.thread_id = thread_id
        self.run_id = str(uuid4())
        self.clock = clock
        self.models = {}
        self.tools = {}
        self.steps = set()
        self.base = {}
        self.last_save = clock()
        self.last_emit = clock()

    async def start(self):
        try:
            self.base = await load(self.thread_id)
        except Exception:
            logger.exception("metrics.load.failed", thread_id=self.thread_id)

    def observe(self, event):
        now = self.clock()
        kind, run = event.get("event", ""), str(event.get("run_id", ""))
        metadata = event.get("metadata") or {}
        # 步编号只在图实例内有意义：用 namespace 区分并行子图，避免相加编号。
        if isinstance(metadata.get("langgraph_step"), int):
            self.steps.add(
                (str(metadata.get("langgraph_checkpoint_ns", "")), metadata["langgraph_step"])
            )
        data = event.get("data") or {}
        if kind == "on_chat_model_start":
            self.models.setdefault(run, {"start": now})
        elif kind == "on_chat_model_stream" and run in self.models:
            chunk = data.get("chunk")
            if (
                getattr(chunk, "content", None)
                or getattr(chunk, "tool_call_chunks", None)
                or getattr(chunk, "additional_kwargs", {}).get("reasoning_content")
            ):
                self.models[run].setdefault("first", now)
        elif kind in ("on_chat_model_end", "on_chat_model_error") and run in self.models:
            model = self.models[run]
            model.setdefault("end", now)
            usage = getattr(data.get("output"), "usage_metadata", None)
            if usage:
                model["usage"] = usage
        elif kind == "on_tool_start" and event.get("name") != "task":
            # task 包含子模型与工具的全部等待；再次计入工具耗时会重复计算。
            self.tools.setdefault(run, {"start": now})
        elif kind in ("on_tool_end", "on_tool_error") and run in self.tools:
            self.tools[run].setdefault("end", now)

    def snapshot(self, finish=False):
        now = self.clock()
        value = {key: 0 for key in FIELDS}
        value.update(
            model_calls=len(self.models), tool_calls=len(self.tools), steps=len(self.steps)
        )
        for model in self.models.values():
            if finish:
                model.setdefault("end", now)
            value["model_seconds"] += max(0, model.get("end", now) - model["start"])
            if "first" in model:
                value["ttft_calls"] += 1
                value["ttft_seconds"] += model["first"] - model["start"]
            usage = model.get("usage")
            if not usage:
                continue
            value["usage_calls"] += 1
            value["input_tokens"] += usage.get("input_tokens", 0)
            value["output_tokens"] += usage.get("output_tokens", 0)
            details = usage.get("input_token_details") or {}
            if "cache_read" in details:
                value["cache_read_tokens"] += details["cache_read"]
                value["cache_input_tokens"] += usage.get("input_tokens", 0)
            seconds = model.get("end", now) - model.get("first", now)
            if seconds > 0:
                value["generation_seconds"] += seconds
                value["speed_tokens"] += usage.get("output_tokens", 0)
        for tool in self.tools.values():
            if finish:
                tool.setdefault("end", now)
            value["tool_seconds"] += max(0, tool.get("end", now) - tool["start"])
        return value

    async def report(self, finish=False):
        now = self.clock()
        if not finish and now - self.last_emit < 1:
            return None
        self.last_emit = now
        value = self.snapshot(finish)
        if finish or now - self.last_save >= 5:
            self.last_save = now
            try:
                async with await connect() as db:
                    await db.execute(
                        """INSERT INTO agent_metrics(thread_id,run_id,payload)
                        VALUES(%s,%s,%s) ON CONFLICT(thread_id,run_id)
                        DO UPDATE SET payload=excluded.payload,updated_at=now()""",
                        (self.thread_id, self.run_id, Jsonb(value)),
                    )
            except Exception:
                logger.exception("metrics.save.failed", thread_id=self.thread_id)
        return {
            "type": "metrics",
            "thread_id": self.thread_id,
            "metrics": combine(self.base, value),
        }
