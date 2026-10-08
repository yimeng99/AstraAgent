"""Chat 端点的 Pydantic 模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ArtifactInfo",
    "Attachment",
    "ChatRequest",
    "SSEEvent",
    "SSEEventType",
    "StreamChatRequest",
]


SSEEventType = Literal[
    "message.start",
    "message.delta",
    # 模型的思维链（<think>…</think>），与正文分开推给前端。
    # 见 core.think：只在展示层分流，历史消息里仍保留原样文本。
    "reasoning.delta",
    # 助手生成的产物（报表 / 文档），前端渲染成下载卡片。
    # 见 core.artifacts：跨轮会持久化，刷新页面后仍能下载。
    "artifact.created",
    "message.end",
    "tool.start",
    "tool.end",
    "error",
    "done",
]


class ArtifactInfo(BaseModel):
    """助手产出的文件（可直接下载）。"""

    file_id: str = Field(..., description="产物 ID，下载地址 /api/v1/files/{file_id}")
    filename: str = Field(..., description="展示用文件名（含后缀）")
    size: int = Field(default=0, ge=0, description="字节数")
    content_type: str = Field(default="", description="MIME 类型")
    url: str = Field(default="", description="下载地址")
    kind: str = Field(default="document", description="image | document")


class Attachment(BaseModel):
    """已上传的附件引用（由 :mod:`api.storage` 落盘后回传）。

    **只接受 ``file_id``** —— 路径一律由服务端解析，前端传路径会被拒绝，
    避免任意文件读取。
    """

    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(
        ...,
        pattern=r"^[0-9a-f]{32}$",
        description="上传时返回的文件 ID。",
    )
    filename: str | None = Field(default=None, max_length=200, description="展示用文件名")
    content_type: str | None = Field(default=None, max_length=100, description="MIME 类型")


class ChatRequest(BaseModel):
    """单轮 chat 请求（同步或流式通用）。"""

    model_config = ConfigDict(extra="forbid")

    user_input: str = Field(
        default="",
        max_length=8192,
        description="用户输入。可为空（纯发图），但须与 attachments 至少有一项非空。",
    )
    thread_id: str | None = Field(
        default=None,
        description="会话 ID（不传则自动生成）。用于 checkpointer 串上下文。",
    )
    attachments: list[Attachment] = Field(
        default_factory=list,
        max_length=8,
        description="已上传的附件引用（最多 8 个）。",
    )

    @model_validator(mode="after")
    def _require_content(self) -> ChatRequest:
        """文本与附件不能同时为空。"""
        if not self.user_input.strip() and not self.attachments:
            raise ValueError("user_input 与 attachments 不能同时为空")
        return self


class StreamChatRequest(ChatRequest):
    """流式 chat 请求（与 ChatRequest 同 schema，预留扩展）。"""

    include_tool_events: bool = Field(
        default=False,
        description="是否推送 tool.start / tool.end 事件（默认关闭，避免泄露内部信息）。",
    )


class SSEEvent(BaseModel):
    """SSE 事件载荷（发给前端）。"""

    type: SSEEventType
    thread_id: str | None = None

    # message.delta / reasoning.delta 字段
    delta: str | None = None

    # artifact.created 字段
    artifact: ArtifactInfo | None = None

    # tool.* 字段
    name: str | None = None
    call_id: str | None = None
    args: dict | None = None
    ok: bool | None = None
    result: str | None = None

    # message.end 字段
    usage: dict | None = None

    # error 字段
    error: str | None = None
