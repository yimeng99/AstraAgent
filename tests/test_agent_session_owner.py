"""在访问图和附件之前拒绝跨用户会话，覆盖普通及 SSE 入口。"""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from api.deps import get_agent, get_config
from api.routes.chat import router
from core.agent import run_once, stream_once
from core.context_type import new_context
from core.sessions import ThreadAccessError, new_thread_id, owned_by_thread_id


@pytest.mark.parametrize("owner", ["alice", "alice-team", "anonymous"])
def test_generated_id_owner(owner):
    tid = new_thread_id(owner)
    assert owned_by_thread_id(tid, owner)
    assert not owned_by_thread_id(tid, "other")


def test_prefix_and_legacy_ids_are_rejected():
    assert not owned_by_thread_id("alice-team-12345678", "alice")
    assert not owned_by_thread_id("unowned", "alice")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_core_rejects_before_graph_access(stream):
    agent = AsyncMock()
    ctx = new_context(user_id="bob")
    with pytest.raises(ThreadAccessError):
        if stream:
            async for _ in stream_once(agent, "test", "alice-12345678", ctx):
                pytest.fail("不应产生事件")
        else:
            await run_once(agent, "test", "alice-12345678", ctx)
    agent.ainvoke.assert_not_called()
    agent.astream_events.assert_not_called()


@pytest.mark.asyncio
async def test_owner_can_invoke():
    agent = AsyncMock()
    agent.config = {"recursion_limit": 125}
    agent.ainvoke.return_value = {"messages": []}
    await run_once(agent, "test", "alice-12345678", new_context(user_id="alice"))
    agent.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_api_rejects_other_owner_before_streaming(path):
    app = FastAPI()
    app.include_router(router)
    agent = AsyncMock()
    app.dependency_overrides[get_agent] = lambda: agent
    app.dependency_overrides[get_config] = lambda: None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            path,
            headers={"X-User-Id": "bob"},
            json={"user_input": "test", "thread_id": "alice-12345678"},
        )
    assert response.status_code == 404
    assert response.json() == {"detail": "对话不存在"}
    agent.ainvoke.assert_not_called()
    agent.astream_events.assert_not_called()
