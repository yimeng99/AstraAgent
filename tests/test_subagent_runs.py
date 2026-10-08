from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command

from api.subagent_runs import SubagentRecorder


@pytest.mark.asyncio
async def test_parallel_details_are_separate_and_link_to_history(monkeypatch):
    recorder = SubagentRecorder("alice-12345678")
    monkeypatch.setattr(recorder, "save", AsyncMock())
    for key in ("a", "b"):
        args = {"description": key, "subagent_type": "general-purpose"}
        await recorder.observe(
            {
                "event": "on_chat_model_end",
                "run_id": "parent",
                "data": {
                    "output": AIMessage(
                        content="", tool_calls=[{"id": "call-" + key, "name": "task", "args": args}]
                    )
                },
            }
        )
        await recorder.observe(
            {"event": "on_tool_start", "run_id": key, "name": "task", "data": {"input": args}}
        )
        await recorder.observe(
            {"event": "on_chat_model_start", "run_id": "model-" + key, "parent_ids": [key]}
        )
    for key, text in [
        ("a", "<think>甲"),
        ("b", "<think>乙</think>正文乙"),
        ("a", "思考</think>正文甲"),
    ]:
        await recorder.observe(
            {
                "event": "on_chat_model_stream",
                "run_id": "model-" + key,
                "parent_ids": [key],
                "data": {"chunk": AIMessageChunk(content=text)},
            }
        )
    for key in ("a", "b"):
        await recorder.observe(
            {"event": "on_chat_model_end", "run_id": "model-" + key, "parent_ids": [key]}
        )
        await recorder.observe(
            {
                "event": "on_tool_end",
                "run_id": key,
                "name": "task",
                "data": {
                    "output": Command(
                        update={
                            "messages": [ToolMessage(content="done", tool_call_id="call-" + key)]
                        }
                    )
                },
            }
        )
    assert recorder.tasks["a"]["messages"][0]["reasoning"] == "甲思考"
    assert recorder.tasks["a"]["messages"][0]["content"] == "正文甲"
    assert recorder.tasks["b"]["messages"][0]["content"] == "正文乙"
    assert recorder.tasks["a"]["call_id"] == "call-a"
    assert recorder.tasks["a"]["status"] == "completed"


@pytest.mark.asyncio
async def test_subagent_api_rejects_other_user(monkeypatch):
    import httpx

    from api import subagent_runs
    from api.main import app

    read = AsyncMock(return_value=None)
    monkeypatch.setattr(subagent_runs, "load", read)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/threads/alice-12345678/subagents/call-a", headers={"X-User-Id": "bob"}
        )
        assert response.status_code == 404
        read.assert_not_called()
