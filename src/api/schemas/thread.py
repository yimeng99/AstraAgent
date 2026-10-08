"""Thread / Message 模型。"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  (Pydantic 运行时需真实类型来解析字段注解)
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.chat import ArtifactInfo  # noqa: TC001  (Pydantic 运行时需真实类型)

__all__ = [
    "Message",
    "MessageRole",
    "Thread",
    "ThreadCreate",
    "ThreadMessages",
]


MessageRole = Literal["user", "assistant", "system", "tool"]


class Message(BaseModel):
    """单条消息。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", description="消息 ID（UUID）。")
    role: MessageRole
    content: str = Field(..., description="文本内容（已脱敏）。")
    reasoning: str = Field(
        default="",
        description="模型思维链（<think> 段）。已从 content 里拆出，前端折叠展示。",
    )
    tools: list[dict[str, str]] = Field(
        default_factory=list, description="助手调用的工具及其结果。"
    )
    failure: dict[str, Any] | None = None
    artifacts: list[ArtifactInfo] = Field(
        default_factory=list,
        description="该消息（所属轮次）生成的文件，前端渲染成下载卡片。",
    )
    attachments: list[ArtifactInfo] = Field(
        default_factory=list,
        description="用户消息携带的附件（从消息里解析还原），前端渲染成文件卡片/预览。",
    )
    created_at: datetime | None = Field(
        default=None,
        description="创建时间。checkpointer 不保证每条消息都带时间，可能为 null。",
    )


class Thread(BaseModel):
    """一个对话线程。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="thread ID")
    title: str = Field(default="新对话", max_length=100)
    created_at: datetime | None = Field(
        default=None, description="创建时间（checkpointer 可能不提供）。"
    )
    updated_at: datetime | None = Field(
        default=None, description="最近更新时间（checkpointer 可能不提供）。"
    )
    message_count: int = Field(default=0, ge=0)


class ThreadMessages(BaseModel):
    """某个对话的完整消息列表。"""

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(..., description="thread ID")
    messages: list[Message] = Field(default_factory=list)


class ThreadCreate(BaseModel):
    """创建新 thread。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=100)


class ThreadRename(BaseModel):
    """用户自定义的会话标题。"""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100, pattern=r"\S")
