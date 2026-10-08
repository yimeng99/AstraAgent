"""附件协议：模型能读内容，历史只展示原文和文件卡片。"""

import base64
import threading

import pytest

from api import attachments
from api.history import split_attachment_context
from api.schemas.chat import Attachment
from core.context_type import MemoryContext
from core.sandbox.attachments import SandboxAttachment

CONTEXT = MemoryContext(user_id="alice", extra={"approval_thread_id": "alice-12345678"})


@pytest.mark.parametrize("vision", [True, False])
async def test_document_content_and_editable_path_share_one_input(monkeypatch, vision):
    reference = Attachment(file_id="a" * 32, filename="记录.txt")
    caller_thread = threading.get_ident()

    def sync(scope, ids, **kwargs):
        assert threading.get_ident() != caller_thread
        assert kwargs["thread_id"] == "alice-12345678"
        return [SandboxAttachment(reference.file_id, "/session/uploads/record.txt", "记录.txt", 6)]

    monkeypatch.setattr(attachments, "resolve_stored_key", lambda _: "stored.txt")
    monkeypatch.setattr(attachments, "load_stored_bytes", lambda _: "文件内容".encode())
    monkeypatch.setattr(attachments, "sync_attachments_to_sandbox", sync)

    content = await attachments.build_user_content(
        "请编辑", [reference], vision=vision, context=CONTEXT
    )
    assert "文件内容" in content
    assert "/session/uploads/record.txt" in content
    user_text, cards = split_attachment_context(content)
    assert user_text == "请编辑"
    assert cards[0]["filename"] == "记录.txt"


async def test_visual_model_receives_image_bytes_without_sandbox(monkeypatch):
    reference = Attachment(file_id="b" * 32, filename="图.png", content_type="text/plain")
    monkeypatch.setattr(attachments, "resolve_stored_key", lambda _: "stored.png")
    monkeypatch.setattr(attachments, "load_stored_bytes", lambda _: b"image bytes")

    def unexpected_sync(*args, **kwargs):
        pytest.fail("内联图片不需要同步沙箱")

    monkeypatch.setattr(attachments, "sync_attachments_to_sandbox", unexpected_sync)
    content = await attachments.build_user_content(
        "描述", [reference], vision=True, context=CONTEXT
    )
    assert content[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(b"image bytes").decode()
    )
    user_text, cards = split_attachment_context(content[0]["text"])
    assert user_text == "描述"
    assert cards[0]["kind"] == "image"


async def test_missing_files_are_reported_and_programming_errors_propagate(monkeypatch):
    reference = Attachment(file_id="c" * 32, filename="missing.txt")

    def broken_storage(_):
        raise TypeError("storage implementation bug")

    monkeypatch.setattr(attachments, "resolve_stored_key", broken_storage)
    with pytest.raises(TypeError, match="storage implementation bug"):
        await attachments.build_user_content("读取", [reference], vision=False, context=CONTEXT)
