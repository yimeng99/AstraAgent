"""RagWiki HTTP 客户端（async httpx）。

POST /api/v1/external/knowledge-bases/retrieval
Headers: X-API-Key: <key>
Body: {"knowledgeBaseId", "query", "retrievalMode", "topK"}
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from core.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RagWikiHit:
    """单条命中（API 返回的 chunk）。"""

    content: str
    score: float = 0.0
    source: str = ""  # 文档标题 / 路径
    metadata: dict[str, Any] | None = None


class RagWikiClient:
    """RagWiki 检索客户端。

    Example:
        >>> client = RagWikiClient()
        >>> hits = await client.retrieve("接口 X 怎么用？")
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        knowledge_base_id: str | None = None,
        timeout_seconds: float = 30.0,
        retrieval_mode: str = "hybrid",
        top_k: int = 8,
    ) -> None:
        self._endpoint = endpoint or os.getenv(
            "RAGWIKI_ENDPOINT",
            "http://localhost:3001/api/v1/external/knowledge-bases/retrieval",
        )
        self._api_key = api_key or os.getenv("RAGWIKI_API_KEY", "")
        self._knowledge_base_id = knowledge_base_id or os.getenv("RAGWIKI_KNOWLEDGE_BASE_ID", "")
        self._timeout = timeout_seconds
        self._mode = retrieval_mode
        self._top_k = top_k
        self._http = httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> RagWikiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._knowledge_base_id)

    async def retrieve(self, query: str, *, top_k: int | None = None) -> list[RagWikiHit]:
        """检索知识库。

        Args:
            query: 用户问题。
            top_k: 覆盖默认 top_k。

        Returns:
            命中列表（按 score 倒序）。

        Raises:
            RuntimeError: 未配置（缺 api_key 或 knowledge_base_id）。
            httpx.HTTPError: 网络 / HTTP 错误。
        """
        if not self.is_configured:
            raise RuntimeError(
                "RagWiki 未配置：请在 .env 设置 RAGWIKI_API_KEY 与 RAGWIKI_KNOWLEDGE_BASE_ID"
            )

        body = {
            "knowledgeBaseId": self._knowledge_base_id,
            "query": query,
            "retrievalMode": self._mode,
            "topK": top_k if top_k is not None else self._top_k,
        }
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self._api_key,
        }

        logger.info("ragwiki.retrieve.start", query_len=len(query), top_k=body["topK"])

        resp = await self._http.post(self._endpoint, json=body, headers=headers)
        resp.raise_for_status()
        payload = resp.json()

        # 兼容多种返回结构：
        #   {"hits": [...]} / {"results": [...]} / {"data": [...]} / 直接 [...]
        items: list[dict[str, Any]] = []
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            for key in ("hits", "results", "data", "chunks"):
                if isinstance(payload.get(key), list):
                    items = payload[key]
                    break
            else:
                items = [payload]

        hits: list[RagWikiHit] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            hits.append(
                RagWikiHit(
                    content=str(it.get("content") or it.get("text") or ""),
                    score=float(it.get("score") or 0.0),
                    source=str(it.get("source") or it.get("title") or it.get("path") or ""),
                    metadata={
                        k: v
                        for k, v in it.items()
                        if k not in {"content", "text", "score", "source", "title", "path"}
                    }
                    or None,
                )
            )

        # 按 score 倒序
        hits.sort(key=lambda h: h.score, reverse=True)
        logger.info(
            "ragwiki.retrieve.done",
            hits=len(hits),
            top_score=hits[0].score if hits else None,
        )
        return hits


# ── 单例工厂（与 checkpointer 风格一致）─────────────────────
_client: RagWikiClient | None = None


def get_ragwiki_client() -> RagWikiClient:
    """获取（或构造）全局 RagWiki 客户端单例。"""
    global _client
    if _client is None:
        _client = RagWikiClient()
    return _client


async def close_ragwiki_client() -> None:
    """关闭全局 RagWiki 客户端（释放连接池）。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
