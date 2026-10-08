"""Checkpointer 获取逻辑：Postgres 优先、连不上退回内存、不静默假装持久化。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.memory import InMemorySaver, MemorySaver

from core import checkpointer as cp

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def _clean() -> None:
    """每条用例前后都清干净（单例是模块级的）。"""
    cp._checkpointer = None
    cp._cm = None
    yield
    cp._checkpointer = None
    cp._cm = None


def test_get_without_init_falls_back_to_memory(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    assert isinstance(cp.get_checkpointer(), MemorySaver)


@pytest.mark.asyncio
async def test_init_without_url_is_memory(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    saver = await cp.init_checkpointer()
    assert isinstance(saver, InMemorySaver)
    assert cp.get_checkpointer() is saver  # 单例


@pytest.mark.asyncio
async def test_init_with_unreachable_url_falls_back(monkeypatch: MonkeyPatch):
    """连不上不能抛，也不能让服务起不来 —— 退回内存版并告警。"""
    monkeypatch.setenv("POSTGRES_URL", "postgresql://u:p@127.0.0.1:1/none")
    saver = await cp.init_checkpointer()
    assert isinstance(saver, InMemorySaver)


@pytest.mark.asyncio
async def test_init_is_idempotent(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    assert await cp.init_checkpointer() is await cp.init_checkpointer()


@pytest.mark.asyncio
async def test_close_is_idempotent(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    await cp.init_checkpointer()
    await cp.close_checkpointer()
    await cp.close_checkpointer()  # 再关一次不能炸
    assert isinstance(cp.get_checkpointer(), MemorySaver)


def test_postgres_when_available(monkeypatch: MonkeyPatch):
    """真连 PG（可选）：设 RUN_PG_TESTS=1 且本机能连上时才跑。

    **同步测试**：psycopg 的异步模式在 Windows 上要求 SelectorEventLoop，而
    pytest-asyncio 的默认 loop 是 Proactor —— 所以这里自建一个 Selector loop 跑
    （uvicorn 带 --reload 启动时用的正是 Selector，与生产一致）。写成本同步用例
    是为了避免"另一个 loop 正在跑"。
    """
    import asyncio
    import os
    import socket
    import sys

    url = os.getenv("POSTGRES_URL", "")
    if os.getenv("RUN_PG_TESTS") != "1" or not url:
        pytest.skip("需要 RUN_PG_TESTS=1 与可用的 POSTGRES_URL")

    host_port = url.rsplit("@", 1)[-1].split("/")[0]
    host, _, port = host_port.partition(":")
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((host, int(port or 5432)))
    except OSError:
        pytest.skip(f"PG 不可达：{host_port}")
    finally:
        sock.close()

    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        saver = loop.run_until_complete(cp.init_checkpointer())
        assert type(saver).__name__ == "AsyncPostgresSaver"
        loop.run_until_complete(cp.close_checkpointer())
    finally:
        loop.close()
