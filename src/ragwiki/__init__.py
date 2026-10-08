"""RagWiki 知识库客户端（HTTP API）。

RagWiki 是独立于飞书的企业知识库后端（localhost:3001），提供检索接口：

    POST /api/v1/external/knowledge-bases/retrieval
    Headers: X-API-Key: <api_key>
    Body: {knowledgeBaseId, query, retrievalMode, topK}

详见 :mod:`core.subagent.ragwiki_agent` 与 :mod:`ragwiki.tools`。
"""

from __future__ import annotations

from ragwiki.client import RagWikiClient, RagWikiHit

__all__ = ["RagWikiClient", "RagWikiHit"]
