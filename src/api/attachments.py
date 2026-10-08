"""在存储边界解析附件，为同步和流式聊天提供相同的模型输入。"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from api.history import ATTACHMENT_CONTEXT_MARKER
from api.storage import UploadRejectedError, load_stored_bytes, resolve_stored_key
from core.documents import (
    MAX_EXTRACT_CHARS_PER_DOC,
    MAX_EXTRACT_CHARS_TOTAL,
    DocumentError,
    detect_format,
    document_block,
    extract_text,
    is_image_suffix,
    mime_for_suffix,
)
from core.sandbox.attachments import sync_attachments_to_sandbox
from core.storage import FILES_URL_PREFIX, StorageError
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from api.schemas.chat import Attachment
    from core.agent import UserContent
    from core.context_type import MemoryContext

logger = get_logger(__name__)
MAX_INLINE_IMAGE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class StoredAttachment:
    """存储后端已解析的附件；格式取服务端保存的后缀。"""

    reference: Attachment
    key: str
    suffix: str

    @property
    def label(self) -> str:
        return self.reference.filename or self.reference.file_id


async def build_user_content(
    user_input: str,
    attachments: list[Attachment],
    *,
    vision: bool,
    context: MemoryContext,
) -> UserContent:
    """图片内联、文档抽文，并提供沙箱中的可编辑文件位置。"""
    if not attachments:
        return user_input

    files, failures = await _resolve_attachments(attachments)
    images = [file for file in files if is_image_suffix(file.suffix)]
    documents = [file for file in files if not is_image_suffix(file.suffix)]
    notes: list[str] = []
    blocks: list[dict[str, Any]] = []
    if vision and images:
        blocks, image_failures = await _image_blocks(images)
        failures.extend(image_failures)
        if blocks:
            notes.append(f"已提供 {len(blocks)} 张图片，可直接查看图片内容。")
    if documents:
        text, document_failures = await _document_text(documents)
        notes.append(text)
        failures.extend(document_failures)

    # 上传存储路径不是容器路径。传输放到线程池，避免阻塞其他会话的 SSE。
    sandbox_files = documents if vision else files
    if sandbox_files:
        notes.append(await asyncio.to_thread(_sandbox_note, sandbox_files, context))
    if failures:
        notes.append("未能处理的附件：" + "；".join(failures))

    manifest = _manifest(attachments, images)
    body = "\n\n".join(note for note in notes if note)
    text = f"{user_input}{ATTACHMENT_CONTEXT_MARKER}{manifest}\n{body}"
    return [{"type": "text", "text": text}, *blocks] if blocks else text


async def _resolve_attachments(
    attachments: list[Attachment],
) -> tuple[list[StoredAttachment], list[str]]:
    files: list[StoredAttachment] = []
    failures: list[str] = []
    for attachment in attachments:
        try:
            key = await asyncio.to_thread(resolve_stored_key, attachment.file_id)
        except (UploadRejectedError, StorageError):
            logger.warning("chat.attachment.missing", file_id=attachment.file_id)
            failures.append(f"{attachment.filename or attachment.file_id}（读取失败）")
            continue
        files.append(StoredAttachment(attachment, key, key.rsplit(".", 1)[-1].lower()))
    return files, failures


async def _image_blocks(
    images: list[StoredAttachment],
) -> tuple[list[dict[str, Any]], list[str]]:
    blocks: list[dict[str, Any]] = []
    failures: list[str] = []
    for image in images:
        try:
            data = await asyncio.to_thread(load_stored_bytes, image.reference.file_id)
        except (UploadRejectedError, StorageError):
            failures.append(f"{image.label}（读取失败）")
            continue
        if len(data) > MAX_INLINE_IMAGE_BYTES:
            failures.append(f"{image.label}（超过 10 MB）")
            continue
        mime = mime_for_suffix(image.suffix)
        encoded = base64.b64encode(data).decode("ascii")
        blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    return blocks, failures


async def _document_text(documents: list[StoredAttachment]) -> tuple[str, list[str]]:
    notes: list[str] = []
    failures: list[str] = []
    budget = MAX_EXTRACT_CHARS_TOTAL
    for document in documents:
        try:
            data = await asyncio.to_thread(load_stored_bytes, document.reference.file_id)
            format_name = detect_format(data[:512], document.key)
            extracted = await asyncio.to_thread(
                extract_text, data, format_name, max_chars=min(MAX_EXTRACT_CHARS_PER_DOC, budget)
            )
        except (DocumentError, UploadRejectedError, StorageError):
            logger.exception("chat.document.failed", file_id=document.reference.file_id)
            failures.append(f"{document.label}（文本提取失败）")
            continue
        notes.append(document_block(extracted, document.label))
        budget -= len(extracted.text)
        if budget <= 0:
            notes.append("本轮文档内容总量已达上限，其余文档未展开。")
            break
    return "\n\n".join(notes), failures


def _sandbox_note(files: list[StoredAttachment], context: MemoryContext) -> str:
    synced = sync_attachments_to_sandbox(
        f"{context.tenant_id}:{context.user_id}",
        [file.reference.file_id for file in files],
        display_names={file.reference.file_id: file.label for file in files},
        thread_id=cast("str", context.extra["approval_thread_id"]),
        context=context,
    )
    paths = {file.file_id: file.sandbox_path for file in synced}
    lines = [
        f"- {file.label}：{paths.get(file.reference.file_id, '未同步到沙箱')}" for file in files
    ]
    return (
        "[附件文件位置]\n"
        + "\n".join(lines)
        + ("\n编辑文件时使用已列出的容器路径；未同步的文件不可通过沙箱读取。")
    )


def _manifest(attachments: list[Attachment], images: list[StoredAttachment]) -> str:
    # 清单紧随标记放在第一行，历史回显据此还原文件卡片，隐藏注入的文档正文。
    image_ids = {image.reference.file_id for image in images}
    items = [
        {
            "file_id": attachment.file_id,
            "filename": attachment.filename or attachment.file_id,
            "kind": "image" if attachment.file_id in image_ids else "document",
            "content_type": attachment.content_type or "",
            "url": f"{FILES_URL_PREFIX}/{attachment.file_id}",
        }
        for attachment in attachments
    ]
    return json.dumps({"attachments": items}, ensure_ascii=False, separators=(",", ":"))
