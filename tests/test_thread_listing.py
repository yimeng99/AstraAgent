"""列表查询不应加载全部检查点或混入子图、其他用户会话。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from core import checkpointer


@pytest.mark.asyncio
async def test_memory_listing_excludes_subgraphs_and_other_owners(monkeypatch):
    class Saver:
        async def alist(self, config):
            for thread, namespace, timestamp in [
                ("alice-12345678", "task:child", "4"),
                ("alice-team-12345678", "", "3"),
                ("alice-12345678", "", "2"),
                ("alice-12345678", "", "1"),
            ]:
                yield SimpleNamespace(
                    config={"configurable": {"thread_id": thread, "checkpoint_ns": namespace}},
                    checkpoint={"ts": timestamp},
                )

    monkeypatch.setattr(checkpointer, "get_checkpointer", Saver)
    assert await checkpointer.list_checkpoint_threads("alice", 100) == {"alice-12345678": "2"}


@pytest.mark.asyncio
async def test_postgres_listing_reads_metadata_without_alist(monkeypatch):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    class Cursor:
        async def execute(self, query, params):
            assert "DISTINCT ON (thread_id)" in query
            assert "checkpoint_ns = ''" in query
            assert "checkpoint_blobs" not in query
            assert params == ("alice", "alice", "alice", "alice", 20)

        async def fetchall(self):
            return [{"thread_id": "alice-12345678", "ts": "2026-10-07"}]

    class Saver(AsyncPostgresSaver):
        def __init__(self):
            pass

        @asynccontextmanager
        async def _cursor(self):
            yield Cursor()

        async def alist(self, *args, **kwargs):
            raise AssertionError("列表不应反序列化全部历史")

    monkeypatch.setattr(checkpointer, "get_checkpointer", Saver)
    assert await checkpointer.list_checkpoint_threads("alice", 20) == {
        "alice-12345678": "2026-10-07"
    }
