"""长期记忆的 namespace：必须按「组织 + 用户」隔离，且单例构造要线程安全。"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from deepagents.backends.utils import create_file_data
from langgraph.store.memory import InMemoryStore

from core import backend as be
from core.context_type import MemoryContext

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


class _Runtime:
    """顶替 LangGraph 的 Runtime：namespace 工厂只用到 ``.context``。"""

    def __init__(self, context: object | None) -> None:
        if context is not None:
            self.context = context


def test_namespace_is_per_user_and_tenant():
    a = be.store_namespace(_Runtime(MemoryContext(user_id="u1", tenant_id="org1")))
    b = be.store_namespace(_Runtime(MemoryContext(user_id="u2", tenant_id="org1")))
    c = be.store_namespace(_Runtime(MemoryContext(user_id="u1", tenant_id="org2")))

    assert a != b, "不同用户不能共用同一份长期记忆"
    assert a != c, "不同组织不能共用同一份长期记忆"
    assert a[:1] == ("memories",)


def test_namespace_without_context_still_isolates_by_default_bucket():
    ns = be.store_namespace(None)
    assert ns == ("memories", "default-org", "anonymous")
    # 绝不能退回一个"所有人共用"的固定 namespace（历史 bug：写死 ("123",)）
    assert "123" not in ns


def test_namespace_ignores_blank_fields():
    ns = be.store_namespace(_Runtime(MemoryContext(user_id="", tenant_id="")))
    assert ns == ("memories", "default-org", "anonymous")


def test_store_singleton_is_thread_safe(monkeypatch: MonkeyPatch):
    """并发首调只能建一个实例（否则会多出一个连接池，且可能被 GC 掉）。"""
    monkeypatch.delenv("POSTGRES_STORE_URL", raising=False)
    be.close_store()

    barrier = threading.Barrier(8)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(lambda: (barrier.wait(), be.get_store())[1]) for _ in range(8)]
        stores = [f.result() for f in futures]

    assert len({id(s) for s in stores}) == 1
    be.close_store()


def test_memory_route_keeps_file_name(monkeypatch: MonkeyPatch):
    store = InMemoryStore()
    monkeypatch.setattr(be, "get_store", lambda: store)
    store.put(be.store_namespace(None), "/AGENTS.md", create_file_data("user preferences"))
    backend = be.get_backend()
    result = backend.download_files(["/memories/AGENTS.md"])[0]
    assert result.error is None
    assert result.content == b"user preferences"
