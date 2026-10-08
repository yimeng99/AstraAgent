"""deepagents Backend 工厂（带路由的 CompositeBackend）。

deepagents 文件工具默认访问当前会话 OpenSandbox，
``/memories/`` 转到 ``StoreBackend`` → ``PostgresStore``
（持久化、跨会话）。``POSTGRES_STORE_URL`` 未设或连不上时退化为内存 store。

长期记忆按「租户 + 用户 + 项目」隔离（见 :func:`store_namespace`）——
早期版本写死了一个固定 namespace，等于所有用户共用一份记忆。
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

from deepagents.backends import CompositeBackend, StoreBackend

from core.sandbox.backend import OpenSandboxBackend
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from langgraph.store.base import BaseStore

logger = get_logger("core.backend")


def _build_in_memory_store() -> BaseStore:
    """未设 ``POSTGRES_STORE_URL`` 时的退路。

    ``InMemoryStore`` 从 ``langgraph.store.memory`` 拿。
    """
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()


def _build_postgres_store() -> tuple[BaseStore, AbstractContextManager[BaseStore]]:
    """构造 ``PostgresStore``（带 setup），并把 context manager 一起返回。

    ⚠️ **必须把 CM 返回给调用方保活**（到 ``close_store``）。它内部是
    ``with Connection.connect(...) as conn: yield cls(conn)``：一旦这个 CM 被
    垃圾回收，生成器终结 → ``with`` 退出 → **底层 psycopg 连接被 close()**，
    而 store 仍攥着这条死连接，此后任何 ``/memories/`` 操作都会抛
    ``psycopg.OperationalError: the connection is closed``。

    连接用 ``pool_config`` 建池而不是单连接：StoreBackend 的方法是同步的，
    会被工作线程并发调用，单连接会撞上 "another command is already in progress"。
    """
    url = os.getenv("POSTGRES_STORE_URL")
    if not url:
        raise RuntimeError("POSTGRES_STORE_URL 未设置")

    from langgraph.store.postgres import PostgresStore

    cm = PostgresStore.from_conn_string(url, pool_config={"min_size": 1, "max_size": 8})
    store = cm.__enter__()
    try:
        store.setup()  # 建表（首次必须）
    except Exception:
        # setup 失败时释放资源
        cm.__exit__(None, None, None)
        raise
    return store, cm


def _build_store() -> tuple[BaseStore, AbstractContextManager[BaseStore] | None]:
    """构造 store：优先 Postgres，失败退化 InMemory。

    Returns:
        ``(store, context_manager)``；内存版没有 CM，返回 ``None``。
    """
    url = os.getenv("POSTGRES_STORE_URL")
    if not url:
        return _build_in_memory_store(), None
    try:
        return _build_postgres_store()
    except Exception as exc:
        logger.warning(
            "postgres_store_unavailable_fallback",
            url=url.split("@")[-1] if "@" in url else url,
            error=str(exc),
        )
        return _build_in_memory_store(), None


# ── 全局单例 ──────────────────────────────────────
_store: BaseStore | None = None
#: Postgres 版的 context manager，**必须活到 close_store**（见 _build_postgres_store）
_store_cm: AbstractContextManager[BaseStore] | None = None
#: StoreBackend 的方法是**同步**的、会被工作线程并发调用，所以懒加载必须加锁：
#: 两个线程同时首调会各建一个 PostgresStore + 各自连接池，其中一个随即被丢弃 ——
#: 它的 CM 被 GC 掉 → 连接关闭，而 `_store` 指着的那个可能正好是它。
_store_lock = threading.Lock()


def get_store() -> BaseStore:
    """获取（或构造）全局 store 单例（线程安全）。"""
    global _store, _store_cm

    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            _store, _store_cm = _build_store()
        return _store


def close_store() -> None:
    """释放 store 资源（Postgres 时真正关闭连接池）。"""
    global _store, _store_cm

    with _store_lock:
        cm, _store_cm = _store_cm, None
        _store = None
    if cm is None:
        return
    try:
        cm.__exit__(None, None, None)
    except Exception as exc:  # pragma: no cover - 关闭阶段尽力而为
        logger.warning("store.close.failed", error=str(exc))


# ── Backend 工厂 ──────────────────────────────────
_default_backend = OpenSandboxBackend()


def store_namespace(runtime: object | None) -> tuple[str, ...]:
    """长期记忆的 namespace：按「租户 + 用户 + 项目」隔离。

    ``Runtime`` 里带着 :class:`core.context_type.MemoryContext`（MCP 拦截器
    也是这么取的）。取不到上下文时退到 ``default-org`` / ``anonymous`` ——
    **绝不能退回一个所有人共用的固定值**，那等于把记忆串给所有用户。
    """
    context = getattr(runtime, "context", None)
    org = str(getattr(context, "tenant_id", "") or "default-org")
    user = str(getattr(context, "user_id", "") or "anonymous")
    project = str(getattr(context, "project_id", "") or "")
    # 无项目时保留历史 namespace；指定项目后独立保存记忆。
    return ("memories", org, user, "projects", project) if project else ("memories", org, user)


def get_backend() -> CompositeBackend:
    """返回 deepagents 用的 CompositeBackend。

    路由表：

    * ``/memories/`` → 长期记忆，包含 AGENTS.md 与 habits.md

    长期记忆落 store（Postgres 时持久化），namespace 见 :func:`store_namespace`；
    其余路径访问当前用户的会话沙箱；沙箱不可用时不回退到宿主机或虚拟文件。
    """
    store = get_store()
    routes = {"/memories/": StoreBackend(namespace=store_namespace, store=store)}
    return CompositeBackend(default=_default_backend, routes=routes)


__all__ = [
    "close_store",
    "get_backend",
    "get_store",
    "store_namespace",
]
