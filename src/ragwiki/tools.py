"""RagWiki @tool 封装（暴露给 agent）。

工具：

* :func:`query_ragwiki` —— 自然语言问题 → RagWiki 检索 → Markdown 片段列表
"""

from __future__ import annotations

from langchain.tools import tool

from core.security import redact, safe_error_message
from core.utils.logging import get_logger
from ragwiki.client import RagWikiHit, get_ragwiki_client

logger = get_logger(__name__)

__all__ = ["format_hits_as_markdown", "query_ragwiki"]


def format_hits_as_markdown(hits: list[RagWikiHit]) -> str:
    """把 hits 列表渲染成 Markdown，便于 LLM 阅读。"""
    if not hits:
        return "（未检索到任何相关内容）"
    parts: list[str] = []
    for i, h in enumerate(hits, start=1):
        score = f"（score={h.score:.3f}）" if h.score else ""
        src = f" — *{h.source}*" if h.source else ""
        parts.append(f"{i}. {h.content}{src} {score}".strip())
    return "\n\n".join(parts)


@tool
def query_ragwiki(query: str, top_k: int = 8) -> str:
    """在 RagWiki 企业知识库中检索与 query 最相关的文档片段。

    Args:
        query: 自然语言问题（中文 / 英文均可）。
        top_k: 返回片段数（默认 8）。

    Returns:
        Markdown 格式的检索结果列表，每个片段含来源与 score。
        如果未配置 API key 或知识库 ID，会返回简短提示。

    Notes:
        RagWiki 与飞书知识库是独立的另一个知识库（你的 RagWiki 项目）。
        本工具只读，不修改任何源文档。

    错误返回已脱敏（不含 env var 名 / API key / 内部路径）。
    """
    logger.info("tool.query_ragwiki", query_len=len(query), top_k=top_k)

    import asyncio

    client = get_ragwiki_client()
    if not client.is_configured:
        # 用户层文案：不暴露环境变量名 / 配置键
        logger.warning("tool.query_ragwiki.not_configured")
        return "RagWiki 知识库暂未配置。请联系管理员启用该功能。"

    try:
        hits = asyncio.run(client.retrieve(query, top_k=top_k))
    except Exception as exc:
        # 详细错误进日志；返回给 LLM 的内容已脱敏
        logger.exception("tool.query_ragwiki.failed", error=redact(str(exc)))
        return f"RagWiki 检索失败：{safe_error_message(exc)}"

    if not hits:
        return "RagWiki 未检索到与该问题相关的文档片段。"

    return format_hits_as_markdown(hits)
