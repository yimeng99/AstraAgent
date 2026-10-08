from types import SimpleNamespace

import pytest

from api.metrics import Collector, combine


def test_parallel_calls_usage_and_duplicate_events():
    now = [0.0]
    collector = Collector("alice-12345678", clock=lambda: now[0])

    def event(kind, run, **data):
        collector.observe(
            {
                "event": kind,
                "run_id": run,
                "data": data,
                "metadata": {"langgraph_step": 2, "langgraph_checkpoint_ns": run},
            }
        )

    event("on_chat_model_start", "a")
    event("on_chat_model_start", "b")
    now[0] = 2
    event("on_chat_model_stream", "a", chunk=SimpleNamespace(content=""))
    assert "first" not in collector.models["a"]
    event("on_chat_model_stream", "a", chunk=SimpleNamespace(content="hello"))
    now[0] = 4
    event("on_chat_model_stream", "b", chunk=SimpleNamespace(content="world"))
    now[0] = 6
    output = SimpleNamespace(
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 40,
            "input_token_details": {"cache_read": 50},
        }
    )
    event("on_chat_model_end", "a", output=output)
    event("on_chat_model_end", "a", output=output)
    event("on_chat_model_end", "b", output=SimpleNamespace(usage_metadata=None))
    result = combine(collector.snapshot())
    assert result["model_calls"] == 2
    assert result["steps"] == 2
    assert result["model_seconds"] == 12
    assert result["ttft"] == 3
    assert result["tps"] == 10
    assert result["total_tokens"] == 140
    assert result["usage_calls"] == 1
    assert result["cache_hit_rate"] == 0.5


def test_unknown_usage_and_interrupted_timing():
    now = [0.0]
    collector = Collector("alice-12345678", clock=lambda: now[0])
    collector.observe({"event": "on_tool_start", "name": "task", "run_id": "parent"})
    collector.observe({"event": "on_tool_start", "name": "write_file", "run_id": "child"})
    collector.observe({"event": "on_chat_model_start", "run_id": "model"})
    now[0] = 5
    result = combine(collector.snapshot(finish=True))
    assert result["tool_calls"] == 1
    assert result["tool_seconds"] == 5
    assert result["total_tokens"] is None
    assert result["tps"] is None
    assert result["cache_hit_rate"] is None
    now[0] = 10
    assert collector.snapshot()["model_seconds"] == 5


@pytest.mark.asyncio
async def test_metrics_api_checks_owner(monkeypatch):
    from unittest.mock import AsyncMock

    import httpx

    from api import metrics
    from api.main import app

    read = AsyncMock(return_value=combine())
    monkeypatch.setattr(metrics, "load", read)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/threads/alice-12345678/metrics", headers={"X-User-Id": "bob"}
        )
        assert response.status_code == 404
        read.assert_not_called()
        response = await client.get(
            "/api/v1/threads/alice-12345678/metrics", headers={"X-User-Id": "alice"}
        )
        assert response.status_code == 200
        assert response.json()["data"]["total_tokens"] is None
