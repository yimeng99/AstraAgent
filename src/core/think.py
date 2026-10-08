"""流式思维链（thinking）分流。

为什么需要：MiniMax-M2/M3 默认把思维链用 ``<think>`` 包在 ``content`` 里透传，
前端会把思考过程当正文渲染，用户直接看到满屏 ``<think>…``。

**只做展示层切分，不做丢弃**：``reasoning`` 片段给折叠的"思考过程"，``text``
走正文，而存进 checkpointer 的**仍是模型原样输出（含标签）** —— MiniMax 要求
多轮工具调用回传完整 assistant 消息，否则交错思维链会断。

难点在流式：标签可能被切在两个 chunk 之间（``"<thi"`` + ``"nk>"``），所以内部
留缓冲区，尾部保留 ``len(最长标签)-1`` 个字符等下一块。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CLOSE_TAGS", "OPEN_TAGS", "ThinkSplitter"]


#: 开场标签。MiniMax M2/M3 用 ``<think>``；vLLM 的 M3 解析器用 ``<mm:think>``；
#: 另有一些开源推理模型用 `` thinking``。
OPEN_TAGS: tuple[str, ...] = ("<think>", "<mm:think>", " thinking")

#: 对应的结束标签。
CLOSE_TAGS: tuple[str, ...] = ("</think>", "</mm:think>", " response")

#: 最长标签长度 —— 决定缓冲区尾部要留多少个字符（防标签被切断）
_MAX_TAG = max(len(t) for t in (*OPEN_TAGS, *CLOSE_TAGS))

#: 片段类型：``text`` = 正文，``reasoning`` = 思考过程
Piece = tuple[str, str]


def _find(buf: str, tags: tuple[str, ...]) -> tuple[int, str]:
    """返回 ``(最早出现的标签位置, 标签)``；没有则 ``(-1, "")``。"""
    best = -1
    best_tag = ""
    for tag in tags:
        idx = buf.find(tag)
        if idx != -1 and (best == -1 or idx < best):
            best, best_tag = idx, tag
    return best, best_tag


def _partial_tail(buf: str, tags: tuple[str, ...]) -> int:
    """缓冲区尾部有多少字符"可能是被切断的标签前缀"，必须留到下一块。

    ``"…<thi"`` 要留 4 个字符；``"…普通文本"`` 留 0 个。
    """
    limit = min(len(buf), _MAX_TAG - 1)
    for keep in range(limit, 0, -1):
        tail = buf[len(buf) - keep :]
        if any(tag.startswith(tail) for tag in tags):
            return keep
    return 0


@dataclass
class ThinkSplitter:
    """增量切分器。

    用法::

        splitter = ThinkSplitter()
        async for chunk in stream:
            for kind, piece in splitter.feed(chunk):
                ...
        for kind, piece in splitter.flush():   # 必须调用，否则尾部 ≤10 字符会丢
            ...
    """

    _buf: str = ""
    _in_think: bool = False

    def feed(self, chunk: str) -> list[Piece]:
        """喂一段增量，返回本轮能确定的片段（可能为空）。"""
        if chunk:
            self._buf += chunk
        return self._drain(final=False)

    def flush(self) -> list[Piece]:
        """流结束：把缓冲区里剩下的都吐出来（未闭合的 think 按 reasoning 处理）。"""
        out = self._drain(final=True)
        if self._buf:
            out.append((self._kind(), self._buf))
            self._buf = ""
        self._in_think = False
        return out

    # ── 内部 ──────────────────────────────────────────

    def _kind(self) -> str:
        return "reasoning" if self._in_think else "text"

    def _drain(self, *, final: bool) -> list[Piece]:
        out: list[Piece] = []
        while True:
            open_idx, open_tag = _find(self._buf, OPEN_TAGS)
            close_idx, close_tag = _find(self._buf, CLOSE_TAGS)

            if self._in_think:
                if close_idx == -1:
                    keep = 0 if final else _partial_tail(self._buf, CLOSE_TAGS)
                    self._take(out, "reasoning", keep)
                    return out
                if close_idx > 0:
                    out.append(("reasoning", self._buf[:close_idx]))
                self._buf = self._buf[close_idx + len(close_tag) :]
                self._in_think = False
                continue

            # 不在思考块里：孤立的结束标签（开场标签在上一轮 / 被截断）直接丢掉，
            # 否则它会作为正文渲染出来。实测 MiniMax 会吐出这种残尾。
            if close_idx != -1 and (open_idx == -1 or close_idx < open_idx):
                if close_idx > 0:
                    out.append(("text", self._buf[:close_idx]))
                self._buf = self._buf[close_idx + len(close_tag) :]
                continue

            if open_idx == -1:
                # 没有完整标签：吐掉除"可能是半个标签"以外的部分。
                # 开场/结束标签的前缀都要留，否则半个 `</think` 会被当正文吐出去。
                keep = 0
                if not final:
                    keep = max(
                        _partial_tail(self._buf, OPEN_TAGS),
                        _partial_tail(self._buf, CLOSE_TAGS),
                    )
                self._take(out, "text", keep)
                return out

            if open_idx > 0:
                out.append(("text", self._buf[:open_idx]))
            self._buf = self._buf[open_idx + len(open_tag) :]
            self._in_think = True

    def _take(self, out: list[Piece], kind: str, keep: int) -> None:
        """把缓冲区里除尾部 ``keep`` 个字符以外的内容作为 ``kind`` 吐出去。"""
        emit = len(self._buf) - keep
        if emit > 0:
            out.append((kind, self._buf[:emit]))
            self._buf = self._buf[emit:]
