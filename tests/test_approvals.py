"""审批与提问共用持久化挂起，替代旧 Event 等待实现的回归测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from core import human
from core.context_type import MemoryContext, new_context
from core.sessions import ThreadAccessError

THREAD = "alice-12345678"
CONFIG = {"configurable": {"thread_id": THREAD}}
CTX = new_context(user_id="alice", tenant_id="default-org", extra={"approval_thread_id": THREAD})


class Model(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture(autouse=True)
def isolated_decisions(tmp_path, monkeypatch):
    monkeypatch.setattr(human, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    human._locks.clear()
    yield
    human._locks.clear()


def make_graph(*, question=False, saver=None, calls=None, resumed=False):
    calls = [] if calls is None else calls

    @tool
    def test_write(value: str) -> str:
        """记录已批准的业务写操作。"""
        calls.append(value)
        return "ok"

    tool_calls = [{"name": "test_write", "args": {"value": "approved"}, "id": "write-1"}]
    if question:
        tool_calls.append(
            {
                "name": "ask_user",
                "args": {"question": "选择格式？", "options": ["Word", "PDF"]},
                "id": "ask-1",
            }
        )
    tools = [test_write, human.ask_user]
    graph = create_agent(
        Model(
            responses=[AIMessage(content="", tool_calls=tool_calls), AIMessage(content="done")],
            i=1 if resumed else 0,
        ),
        tools=tools,
        middleware=[human.HumanInteractionMiddleware(tools)],
        context_schema=MemoryContext,
        checkpointer=saver or InMemorySaver(),
    )
    return graph, calls


async def start(graph):
    return await graph.ainvoke(
        {"messages": [{"role": "user", "content": "test"}]}, CONFIG, context=CTX
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("approve", [True, False])
async def test_suspend_restore_and_replay(approve):
    saver = InMemorySaver()
    graph, calls = make_graph(saver=saver)
    result = await start(graph)
    assert result["__interrupt__"] and calls == []
    item = (await human.pending(graph, CTX, THREAD))["approvals"][0]
    assert item["expires_at"] is None
    command = await human.prepare_resume(graph, CTX, THREAD, item["id"], approve=approve)
    # 重建图后仍能读取断点和已落库的回答，不依赖旧请求或进程内 Event。
    restored, _ = make_graph(saver=saver, calls=calls, resumed=True)
    ready = (await human.pending(restored, CTX, THREAD))["approvals"][0]
    assert ready["resume_ready"]
    command = await human.prepare_resume(restored, CTX, THREAD, ready["id"], approve=approve)
    await restored.ainvoke(command, CONFIG, context=CTX)
    assert calls == (["approved"] if approve else [])
    assert await human.pending(restored, CTX, THREAD) == {"approvals": [], "questions": []}
    with pytest.raises(human.HumanConflictError):
        await human.prepare_resume(restored, CTX, THREAD, item["id"], approve=approve)


@pytest.mark.asyncio
async def test_partial_answers_survive_refresh():
    graph, calls = make_graph(question=True)
    await start(graph)
    items = await human.pending(graph, CTX, THREAD)
    approval, question = items["approvals"][0], items["questions"][0]
    assert await human.prepare_resume(graph, CTX, THREAD, approval["id"], approve=True) is None
    refreshed = await human.pending(graph, CTX, THREAD)
    assert refreshed["approvals"] == [] and refreshed["questions"] == [question]
    assert calls == []
    with pytest.raises(human.HumanConflictError):
        await human.prepare_resume(graph, CTX, THREAD, approval["id"], approve=True)
    with pytest.raises(human.HumanInputError):
        await human.prepare_resume(graph, CTX, THREAD, question["id"], answer=" ")
    command = await human.prepare_resume(graph, CTX, THREAD, question["id"], answer="其他格式")
    result = await graph.ainvoke(command, CONFIG, context=CTX)
    assert calls == ["approved"]
    assert any("其他格式" in str(m.content) for m in result["messages"] if m.type == "tool")


@pytest.mark.asyncio
async def test_identity_and_digest_rejected():
    graph, calls = make_graph()
    result = await start(graph)
    item = (await human.pending(graph, CTX, THREAD))["approvals"][0]
    for ctx in [new_context(user_id="bob"), new_context(user_id="alice", tenant_id="other")]:
        with pytest.raises(ThreadAccessError):
            await human.pending(graph, ctx, THREAD)
        with pytest.raises(ThreadAccessError):
            await human.prepare_resume(graph, ctx, THREAD, item["id"], approve=True)
    interrupt = result["__interrupt__"][0]
    with pytest.raises(ValueError, match="参数"):
        await graph.ainvoke(
            Command(resume={interrupt.id: {"write-1": {"approve": True, "digest": "wrong"}}}),
            CONFIG,
            context=CTX,
        )
    assert calls == []


@pytest.mark.asyncio
async def test_execution_guard_and_read_policy():
    middleware = human.HumanInteractionMiddleware([])
    req = SimpleNamespace(
        tool_call={"id": "x", "name": "write_file", "args": {}},
        tool=None,
        runtime=SimpleNamespace(context=CTX),
        state={"messages": []},
    )
    handler = AsyncMock()
    assert (await middleware.awrap_tool_call(req, handler)).status == "error"
    handler.assert_not_called()
    req.tool_call["name"] = "query_ragwiki"
    await middleware.awrap_tool_call(req, handler)
    handler.assert_awaited_once()
    read = SimpleNamespace(metadata={"approval_mode": "read_only"})
    assert human.needs_approval("mcp__remote__write", read)
    assert human.needs_approval("ask_user", read)
    assert not human.needs_approval("business_read", read)
    assert human.display_args({"nested": [{"token": "secret"}]}) == {
        "nested": [{"token": "[已隐藏敏感值]"}]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["write_file", "edit_file"])
async def test_session_files_execute_without_interrupt(name):
    ctx = CTX.model_copy(update={"permissions": frozenset({"read"})})
    middleware = human.HumanInteractionMiddleware([])
    call = {"id": "chapter", "name": name, "args": {"file_path": "/dissertation/02.txt"}}
    state = {"messages": [AIMessage(content="", tool_calls=[call])]}
    runtime = SimpleNamespace(context=ctx)
    assert await middleware.aafter_model(state, runtime) == {"human_decisions": {}}
    handler = AsyncMock(return_value="written")
    request = SimpleNamespace(tool_call=call, tool=None, runtime=runtime, state=state)
    assert await middleware.awrap_tool_call(request, handler) == "written"
    handler.assert_awaited_once()


@pytest.mark.parametrize(
    "path",
    [
        "/memories/AGENTS.md",
        "memories/preferences.txt",
        "/workspace/skills/test.md",
        "../other.txt",
        "/workspace/sessions/other/file.txt",
        "",
    ],
)
def test_protected_files_still_require_approval(path):
    ctx = CTX.model_copy(update={"permissions": frozenset({"read"})})
    assert human.needs_approval("write_file", None, {"file_path": path}, ctx)


def test_session_write_requires_owned_context():
    args = {"file_path": "chapter.txt"}
    assert human.needs_approval("write_file", None, args, CTX)
    ctx = CTX.model_copy(update={"permissions": frozenset({"read"}), "user_id": "bob"})
    assert human.needs_approval("write_file", None, args, ctx)
    assert human.needs_approval("import_session_file", None, args, ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_api_resume_owner_and_legacy_endpoint(monkeypatch, batch):
    from api import run_store
    from api.deps import get_agent
    from api.main import app

    graph, calls = make_graph()
    await start(graph)
    monkeypatch.setitem(app.dependency_overrides, get_agent, lambda: graph)
    # API 协议测试不连接开发数据库，仍执行真实的后台恢复流程。
    lease = AsyncMock()
    acquire = AsyncMock(return_value=lease)
    monkeypatch.setattr(run_store, "acquire", acquire)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-User-Id": "alice"}
        url = f"/api/v1/threads/{THREAD}"
        response = await client.get(url + "/interactions", headers=headers)
        assert response.status_code == 200
        assert response.json()["code"] == "0"
        item = response.json()["data"]["approvals"][0]
        response = await client.get(url + "/interactions", headers={"X-User-Id": "bob"})
        assert response.status_code == 404
        response = await client.post("/api/v1/approvals/old/decision", json={"approve": True})
        assert response.status_code == 410 and calls == []
        response = await client.post(
            url + "/resume", headers=headers, json={"id": item["id"], "approve": "true"}
        )
        assert response.status_code == 422
        response = await client.post(
            url + "/resume",
            headers=headers,
            json={"ids": [item["id"]], "approve": True}
            if batch
            else {"id": item["id"], "approve": True},
        )
        assert response.status_code == 200 and '"type": "done"' in response.text
        assert calls == ["approved"]
        acquire.assert_awaited_once_with(THREAD)
        lease.close.assert_awaited_once()
        response = await client.post(
            url + "/resume", headers=headers, json={"id": item["id"], "approve": True}
        )
        assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("approve", [True, False])
async def test_batch_approval_restores_parallel_interrupts(approve):
    def batch(i):
        return SimpleNamespace(
            id=i,
            value={
                "kind": "human",
                "thread_id": THREAD,
                "user_id": CTX.user_id,
                "org_id": CTX.tenant_id,
                "project_id": CTX.project_id,
                "items": [
                    {
                        "kind": "approval",
                        "call_id": i,
                        "digest": i,
                        "tool": "test_write",
                        "args": {},
                    }
                ],
            },
        )

    graph = SimpleNamespace(
        aget_state=AsyncMock(
            return_value=SimpleNamespace(interrupts=[batch("child-a"), batch("child-b")])
        )
    )
    with pytest.raises(human.HumanConflictError):
        await human.prepare_approval_batch(graph, CTX, THREAD, ["child-a:0", "stale:0"], approve)
    assert human._responses(CTX, THREAD, "child-a") == {}
    command = await human.prepare_approval_batch(
        graph, CTX, THREAD, ["child-a:0", "child-b:0"], approve
    )
    assert set(command.resume) == {"child-a", "child-b"}
    assert command.resume["child-a"]["child-a"]["approve"] is approve
    # 重试请求不能反转已经落库的决定。
    repeated = await human.prepare_approval_batch(
        graph, CTX, THREAD, ["child-a:0", "child-b:0"], not approve
    )
    assert repeated.resume == command.resume


@pytest.mark.asyncio
async def test_batch_approval_does_not_answer_questions():
    graph, calls = make_graph(question=True)
    await start(graph)
    items = await human.pending(graph, CTX, THREAD)
    approval, question = items["approvals"][0], items["questions"][0]
    with pytest.raises(human.HumanInputError):
        await human.prepare_approval_batch(
            graph, CTX, THREAD, [approval["id"], question["id"]], True
        )
    assert await human.prepare_approval_batch(graph, CTX, THREAD, [approval["id"]], True) is None
    assert calls == []
    assert (await human.pending(graph, CTX, THREAD))["questions"] == [question]
    command = await human.prepare_resume(graph, CTX, THREAD, question["id"], answer="Word")
    await graph.ainvoke(command, CONFIG, context=CTX)
    assert calls == ["approved"]


@pytest.mark.asyncio
async def test_legacy_parallel_decisions_can_be_read_after_reload():
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(human.HumanState)
    builder.add_node("a", lambda state: {"human_decisions": {"a": {"digest": "a"}}})
    builder.add_node("b", lambda state: {"human_decisions": {"b": {"digest": "b"}}})
    for name in ("a", "b"):
        builder.add_edge(START, name)
        builder.add_edge(name, END)
    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    await graph.ainvoke({"messages": []}, CONFIG)
    restored = builder.compile(checkpointer=saver)
    state = await restored.aget_state(CONFIG)
    assert set(state.values["human_decisions"]) == {"a", "b"}


def test_approval_state_is_private_to_each_agent():
    from typing import get_type_hints

    from langchain.agents.middleware.types import PrivateStateAttr

    hint = get_type_hints(human.HumanState, include_extras=True)["human_decisions"]
    assert PrivateStateAttr in hint.__args__[0].__metadata__
