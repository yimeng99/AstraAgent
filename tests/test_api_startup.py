"""Web 持久化不可用时，启动必须失败并释放已创建的 agent。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from api import main


async def test_run_store_failure_does_not_report_ready(monkeypatch):
    closed = []

    @asynccontextmanager
    async def core_lifespan(config):
        try:
            yield object()
        finally:
            closed.append("agent")

    monkeypatch.setattr(main, "load_app_config", lambda: SimpleNamespace(tracing=object()))
    monkeypatch.setattr(main, "init_tracing", Mock())
    monkeypatch.setattr(main, "shutdown_tracing", lambda: closed.append("tracing"))
    monkeypatch.setattr(main, "core_lifespan", core_lifespan)
    monkeypatch.setattr(
        main, "setup_runs", AsyncMock(side_effect=RuntimeError("database unavailable"))
    )
    application = FastAPI()

    with pytest.raises(RuntimeError, match="database unavailable"):
        async with main.lifespan(application):
            pytest.fail("持久化初始化失败不应对外就绪")

    assert application.state.ready is False
    assert closed == ["agent", "tracing"]
