"""模型可修正的业务输入与工具实现错误必须分开。"""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.tools import ToolException

from business.investment.tools.research import run_investment_research
from business.investment.tools.review import investment_review_project
from core import report_tools
from core.context_type import MemoryContext
from core.sandbox import files


@pytest.mark.parametrize(
    "arguments",
    [
        {"company_name": " "},
        {"company_name": "A", "project": {"company_name": "B"}},
        {
            "company_name": "A",
            "project": {"company_name": "A", "park_name": "park-a"},
            "rules": {
                "park_name": "park-b",
                "version": "1",
                "source": "user",
                "investment_basis": "total",
            },
        },
    ],
)
async def test_research_rejects_fixable_input_as_tool_error(arguments):
    with pytest.raises(ToolException):
        await run_investment_research.ainvoke(arguments)


def test_review_rejects_rules_for_another_park_as_tool_error():
    with pytest.raises(ToolException, match="园区"):
        investment_review_project.invoke(
            {
                "project": {"company_name": "A", "park_name": "park-a"},
                "rules": {
                    "park_name": "park-b",
                    "version": "1",
                    "source": "user",
                    "investment_basis": "total",
                },
            }
        )


@pytest.fixture
def report_context(monkeypatch):
    monkeypatch.setattr(
        report_tools,
        "get_runtime_context",
        lambda: MemoryContext(
            user_id="alice",
            permissions=frozenset({"read"}),
            extra={"approval_thread_id": "alice-12345678"},
        ),
    )


@pytest.mark.parametrize(
    "paths,content",
    [
        (["part.txt", "part.txt"], b"text"),
        (["part.docx"], b"text"),
        (["part.txt"], b" "),
        (["part.txt"], b"\xff\xfe\x00"),
    ],
)
def test_invalid_report_source_is_fixable(monkeypatch, report_context, paths, content):
    monkeypatch.setattr("core.sandbox.files.read_session_files", lambda *args, **kwargs: [content])
    with pytest.raises(ToolException):
        report_tools._sections_from_files(paths)


@pytest.mark.parametrize(
    "path,payload,available,message",
    [
        ("../part.txt", {}, True, "相对路径"),
        ("/part.txt", {}, True, "相对路径"),
        ("part.txt", {}, False, "沙箱暂不可用"),
        ("part.txt", {"ok": False, "status": 404, "detail": "文件不存在"}, True, "文件不存在"),
        ("part.txt", {"ok": True, "size": 4 * 1024 * 1024 + 1}, True, "总大小超过"),
    ],
)
def test_report_source_read_failure_is_fixable(
    monkeypatch, report_context, path, payload, available, message
):
    result = SimpleNamespace(
        exit_code=0, logs=SimpleNamespace(stdout=[SimpleNamespace(text=json.dumps(payload))])
    )
    sandbox = Mock()
    sandbox.commands.run.return_value = result
    manager = Mock()
    manager.acquire.return_value = nullcontext(sandbox)
    monkeypatch.setattr(files, "get_sandbox_manager", lambda: manager if available else None)
    render = Mock()
    monkeypatch.setattr(report_tools, "_render_document", render)

    receipt = json.loads(
        report_tools.render_document_from_files.invoke(
            {"title": "report", "filename": "report.docx", "source_files": [path]}
        )
    )

    assert receipt["state"] == "error"
    assert message in receipt["error"]
    render.assert_not_called()


@pytest.mark.parametrize("error_type", [TypeError, RuntimeError])
def test_report_source_bug_propagates(monkeypatch, report_context, error_type):
    monkeypatch.setattr(
        "core.sandbox.files.read_session_files", Mock(side_effect=error_type("broken reader"))
    )
    with pytest.raises(error_type, match="broken reader"):
        report_tools.render_document_from_files.invoke(
            {"title": "report", "filename": "report.docx", "source_files": ["part.txt"]}
        )
