"""``<think>`` 流式分流器的单元测试。

重点覆盖流式才有的坑：标签被切成两半、多个思考块、只有孤立的结束标签、
思考块没闭合就结束。
"""

from __future__ import annotations

import pytest

from core.think import ThinkSplitter

Piece = tuple[str, str]


def run(chunks: list[str]) -> tuple[str, str]:
    """按给定分块喂进去，返回 ``(正文, 思考)``。"""
    splitter = ThinkSplitter()
    text = ""
    reasoning = ""
    for chunk in chunks:
        for kind, piece in splitter.feed(chunk):
            if kind == "text":
                text += piece
            else:
                reasoning += piece
    for kind, piece in splitter.flush():
        if kind == "text":
            text += piece
        else:
            reasoning += piece
    return text, reasoning


def run_char_by_char(raw: str) -> tuple[str, str]:
    return run(list(raw))


def test_plain_text_passes_through():
    assert run(["你好，", "世界"]) == ("你好，世界", "")


def test_plain_text_char_by_char_is_not_delayed_or_lost():
    # 逐字符喂：缓冲区必须把"可能是半个标签"的部分留住，同时不吞正文
    assert run_char_by_char("abcdefg") == ("abcdefg", "")


def test_think_block_is_split_out():
    text, reasoning = run(["<think>想一想</think>答案"])
    assert text == "答案"
    assert reasoning == "想一想"


def test_think_block_char_by_char():
    # 标签被切成两半：`<thi` + `nk>`，必须还能识别
    text, reasoning = run_char_by_char("<think>想</think>答")
    assert text == "答"
    assert reasoning == "想"


def test_realistic_stream_split_at_tag_boundary():
    chunks = ["<thi", "nk>用户问", "的是 A", "</thi", "nk>最终回答"]
    assert run(chunks) == ("最终回答", "用户问的是 A")


def test_text_before_and_after_think():
    text, reasoning = run(["\n前", "<think>中</think>", "后"])
    assert text == "\n前后"
    assert reasoning == "中"


def test_multiple_think_blocks():
    text, reasoning = run(["<think>一</think>A<think>二</think>B"])
    assert text == "AB"
    assert reasoning == "一二"


def test_stray_closing_tag_is_dropped():
    # 用户第一张截图里的情况：开场标签在上文，这里只剩一个 </think>
    assert run(["OK 差不多。直接给。 </think>然后开始"]) == ("OK 差不多。直接给。 然后开始", "")


def test_unclosed_think_is_flushed_as_reasoning():
    assert run(["<think>没写完"]) == ("", "没写完")


def test_mm_think_variant():
    assert run(["<mm:think>想</mm:think>答"]) == ("答", "想")


@pytest.mark.parametrize("size", [1, 2, 3, 5, 7])
def test_chunking_never_loses_content(size: int):
    raw = "开头<think>思考内容</think>结尾<think>第二段思考</think>收尾"
    chunks = [raw[i : i + size] for i in range(0, len(raw), size)]
    text, reasoning = run(chunks)
    assert text == "开头结尾收尾"
    assert reasoning == "思考内容第二段思考"


def test_pieces_are_non_empty():
    splitter = ThinkSplitter()
    for kind, piece in splitter.feed("<think>a</think>b"):
        assert kind in {"text", "reasoning"}
        assert piece != ""
    for _, piece in splitter.flush():
        assert piece != ""


def test_reusable_after_flush():
    splitter = ThinkSplitter()
    splitter.feed("<think>一</think>答")
    splitter.flush()
    assert [p for _, p in splitter.feed("下一轮")] == ["下一轮"]
