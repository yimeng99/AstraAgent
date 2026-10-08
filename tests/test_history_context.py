"""「用户原话 vs 注入的附件上下文」的拆分测试。

背景：文档正文是拼进用户消息里给模型看的；如果历史回显照单全收，用户消息
里会糊一整篇文档正文，连对话标题都会被污染（见 api/history 的
ATTACHMENT_CONTEXT_MARKER）。
"""

from __future__ import annotations

import json

import pytest

from api.attachments import build_user_content
from api.history import ATTACHMENT_CONTEXT_MARKER, split_attachment_context
from api.schemas.chat import Attachment
from core.context_type import MemoryContext

ATT = Attachment(file_id="a" * 32, filename="班级名单表.xlsx", content_type="")


def test_no_marker_returns_text_as_is():
    assert split_attachment_context("就这一句") == ("就这一句", [])


def test_marker_splits_user_text_and_manifest():
    manifest = json.dumps(
        {
            "attachments": [
                {
                    "file_id": "a" * 32,
                    "filename": "班级名单表.xlsx",
                    "kind": "document",
                    "content_type": "",
                    "url": f"/api/v1/files/{'a' * 32}",
                }
            ]
        },
        ensure_ascii=False,
    )
    raw = f"分析一下这个{ATTACHMENT_CONTEXT_MARKER}{manifest}\n[文档：班级名单表.xlsx]\n正文……"

    user_text, attachments = split_attachment_context(raw)
    assert user_text == "分析一下这个"
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "班级名单表.xlsx"
    assert "正文" not in user_text


def test_marker_without_manifest_still_strips_context():
    raw = f"你好{ATTACHMENT_CONTEXT_MARKER}老消息没有清单行\n[文档：x.pdf]"
    user_text, attachments = split_attachment_context(raw)
    assert user_text == "你好"
    assert attachments == []


def test_empty_user_text_keeps_empty():
    raw = f'{ATTACHMENT_CONTEXT_MARKER}{{"attachments": []}}\n[用户上传了图片]'
    user_text, _ = split_attachment_context(raw)
    assert user_text == ""


def test_malformed_manifest_is_tolerated():
    raw = f"提问{ATTACHMENT_CONTEXT_MARKER}{{不是 json}}\n后面还有内容"
    user_text, attachments = split_attachment_context(raw)
    assert user_text == "提问"
    assert attachments == []


@pytest.mark.asyncio
async def test_build_user_content_marks_context_and_keeps_manifest():
    content = await build_user_content(
        "分析一下这个", [ATT], vision=False, context=MemoryContext(user_id="alice")
    )
    assert isinstance(content, str)
    assert ATTACHMENT_CONTEXT_MARKER in content

    user_text, attachments = split_attachment_context(content)
    assert user_text == "分析一下这个"  # 回显时只剩用户说的话
    assert [a["file_id"] for a in attachments] == [ATT.file_id]
    assert attachments[0]["url"].endswith(ATT.file_id)

    # 给模型的那一份里，附件说明必须还在（这里文件不存在，走的是"读取失败"降级分支）
    assert "未能处理的附件" in content
    assert "班级名单表.xlsx" in content


@pytest.mark.asyncio
async def test_build_user_content_without_attachments_has_no_marker():
    content = await build_user_content(
        "纯文字提问", [], vision=True, context=MemoryContext(user_id="alice")
    )
    assert content == "纯文字提问"
    assert ATTACHMENT_CONTEXT_MARKER not in content
