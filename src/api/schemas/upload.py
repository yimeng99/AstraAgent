"""Upload 端点的 Pydantic 模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["UploadResponse"]


UploadKind = Literal["image", "document"]


class UploadResponse(BaseModel):
    """上传成功后的回执。

    前端拿到 ``file_id`` / ``preview_url`` 后，在发消息时以 attachments 传给
    后端。``preview_url`` 已是**可直接使用**的地址：本地后端给
    ``/api/v1/files/{id}``，OSS 后端给带签名的临时 URL（含有效期，前端
    不要缓存复用）。

    ``kind`` 区分图片与文档：图片前端可以直接预览、后端可以走多模态；
    文档（PDF/Word/Excel）后端会在发消息前抽成文本。
    """

    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(..., description="本次上传的唯一 ID（回传用）")
    filename: str = Field(..., description="原始文件名（已做安全清洗）")
    content_type: str = Field(..., description="MIME 类型（按魔数判定，非客户端自报）")
    size: int = Field(..., ge=0, description="字节数")
    key: str = Field(..., description="存储后端内的对象 key（服务端生成）")
    kind: UploadKind = Field(default="image", description="附件类别：image | document")
    preview_url: str | None = Field(
        default=None,
        description="可直接用于 <img src> 的 URL。OSS 为带签名的临时地址，勿长期缓存。",
    )
