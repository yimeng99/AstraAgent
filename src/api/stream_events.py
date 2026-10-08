"""把 LangChain v2 事件转换为聊天事件，保留主回复独立的展示状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from api.utils.messages import text_of, tool_result_failed, tool_result_text
from core.mcp.registry import emits_tool_events
from core.think import ThinkSplitter

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage, AIMessageChunk
    from langchain_core.runnables.schema import StreamEvent

__all__ = ["Event", "StreamState", "wants_tool_event"]

type Event = dict[str, Any]


def wants_tool_event(include_tool_events: bool, name: str) -> bool:
    """外部 MCP 调用默认展示进度，避免等待期间界面毫无反馈。"""
    return include_tool_events or emits_tool_events(name)


@dataclass
class StreamState:
    """一轮执行的展示状态；partial 字段只保存最近一段主模型输出。"""

    thread_id: str
    include_tool_events: bool
    partial_text: str = ""
    partial_reasoning: str = ""
    partial_id: str = ""
    total_chars: int = 0
    reasoning_chars: int = 0
    stage: str = "agent"
    failed_tool: str = ""
    active_tools: dict[str, str] = field(default_factory=dict)
    delegated_runs: set[str] = field(default_factory=set)
    splitter: ThinkSplitter = field(default_factory=ThinkSplitter)

    def convert(self, raw: StreamEvent) -> list[Event]:
        """消费一条 SDK 事件；子任务事件由独立 recorder 处理。"""
        kind, name, run_id, data = raw["event"], raw["name"], raw["run_id"], raw["data"]
        if kind == "on_tool_start" and name == "task":
            self.delegated_runs.add(run_id)
        # 子图名称和层数不稳定，祖先 run_id 才能隔离嵌套任务和模型重试。
        if self.delegated_runs.intersection(raw["parent_ids"]):
            return []

        match kind:
            case "on_chat_model_start":
                events = self.flush()
                self.splitter = ThinkSplitter()
                self.partial_text = self.partial_reasoning = self.partial_id = ""
                self.failed_tool = ""
                self.stage = "model"
                return [*events, self._event("assistant.start")]
            case "on_chat_model_stream":
                chunk = cast("AIMessageChunk", data["chunk"])
                self.partial_id = chunk.id or self.partial_id
                return self._pieces(self.splitter.feed(text_of(chunk.content)))
            case "on_chat_model_end":
                output = cast("AIMessage", data["output"])
                self.partial_id = output.id or self.partial_id
                self.stage = "agent"
            case "on_tool_start":
                self.active_tools[run_id] = name
                self.stage = "tool"
                if wants_tool_event(self.include_tool_events, name):
                    return [self._event("tool.start", name=name, call_id=run_id)]
            case "on_tool_end" | "on_tool_error":
                self.active_tools.pop(run_id)
                if kind == "on_tool_error":
                    self.failed_tool = name
                self.stage = "tool" if self.active_tools or self.failed_tool else "agent"
                if wants_tool_event(self.include_tool_events, name):
                    return [self._tool_end(raw)]
            case "on_custom_event":
                return self._custom_event(name, cast("dict[str, Any]", data))
        return []

    def flush(self) -> list[Event]:
        """输出缓冲的标签残片，失败落盘之前也必须调用。"""
        return self._pieces(self.splitter.flush())

    def end_event(self) -> Event:
        """返回整轮主模型正文和思考的累计字符数。"""
        return self._event(
            "message.end",
            usage={"total_chars": self.total_chars, "reasoning_chars": self.reasoning_chars},
        )

    def _pieces(self, pieces: list[tuple[str, str]]) -> list[Event]:
        events: list[Event] = []
        for channel, text in pieces:
            if not text:
                continue
            if channel == "reasoning":
                self.partial_reasoning += text
                self.reasoning_chars += len(text)
                events.append(self._event("reasoning.delta", delta=text))
            else:
                self.partial_text += text
                self.total_chars += len(text)
                events.append(self._event("message.delta", delta=text))
        return events

    def _tool_end(self, raw: StreamEvent) -> Event:
        failed = raw["event"] == "on_tool_error"
        output = None if failed else raw["data"]["output"]
        return self._event(
            "tool.end",
            name=raw["name"],
            call_id=raw["run_id"],
            ok=not failed and not tool_result_failed(output, raw["name"]),
            result="工具执行失败，请查看服务端日志。" if failed else tool_result_text(output),
        )

    def _custom_event(self, name: str, data: dict[str, Any]) -> list[Event]:
        if name in {"approval.updated", "question.updated"}:
            if data["thread_id"] == self.thread_id:
                payload_key = "approval" if name == "approval.updated" else "question"
                return [self._event(name, **{payload_key: data})]
        elif name == "investment.progress":
            return [self._event("research.progress", stage=data["stage"], message=data["message"])]
        return []

    def _event(self, event_type: str, **payload: object) -> Event:
        return {"type": event_type, "thread_id": self.thread_id, **payload}
