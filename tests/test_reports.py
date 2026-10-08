"""报表渲染（core.reports）与产物通道（core.artifacts）的测试。

产物落库会用临时目录里的 LocalBackend，不往 ``workspace/uploads`` 里拉屎。
"""

from __future__ import annotations

import io

import pytest

from core import artifacts as artifacts_mod
from core.artifacts import Artifact, load_thread_artifacts, save_artifact, take_pending
from core.reports import (
    SectionSpec,
    SheetSpec,
    TableSpec,
    describe_for_verification,
    render_docx,
    render_pdf,
    render_xlsx,
)
from core.storage import LocalBackend

SHEETS = [
    SheetSpec(
        name="销售明细[非法字符]",
        table=TableSpec(
            title="2026 Q3 销售明细",
            headers=["区域", "销售额", "增长率"],
            rows=[
                ["华东", 1234000, 0.18],
                ["华南", 890000, -0.05],
                ["合计", "=SUM(B2:B3)", None],
            ],
        ),
    ),
    SheetSpec(name="名单", table=TableSpec(headers=["姓名", "分数"], rows=[["张三", 91]])),
]

SECTIONS = [
    SectionSpec(heading="一、概览", paragraphs=["本季度营收 1234 万元。"], bullets=["华东最大"]),
    SectionSpec(
        heading="二、明细",
        table=TableSpec(headers=["区域", "销售额"], rows=[["华东", 1234000], ["华南", 890000]]),
    ),
]


# ── xlsx ─────────────────────────────────────────


def test_render_xlsx_structure_and_formatting():
    import openpyxl

    data = render_xlsx(SHEETS)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    try:
        # 默认空表被移除，只剩我们给的页；工作表名里的 [] 被过滤掉
        assert wb.sheetnames == ["销售明细非法字符", "名单"]

        ws = wb["销售明细非法字符"]
        assert ws["A1"].value == "2026 Q3 销售明细"  # 表标题占第一行
        assert ws["A2"].value == "区域"  # 表头
        assert ws["A2"].font.bold is True
        assert ws["B3"].value == 1234000
        assert ws["B3"].number_format == "#,##0"  # 整数带千分位
        assert ws["C3"].value == 0.18
        assert ws["C3"].number_format == "#,##0.00"
        assert ws["B5"].value == "=SUM(B2:B3)"  # 公式原样写入
        assert ws.freeze_panes == "A3"  # 冻结表头下第一行
        assert ws.auto_filter.ref.startswith("A2:")
        assert ws.column_dimensions["A"].width >= 8
    finally:
        wb.close()


def test_render_xlsx_requires_a_sheet():
    with pytest.raises(ValueError):
        render_xlsx([])


# ── docx ─────────────────────────────────────────


def test_render_docx_contents():
    from docx import Document

    data = render_docx("季度报告", SECTIONS, subtitle="内部资料")
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "季度报告" in text
    assert "内部资料" in text
    assert "一、概览" in text and "本季度营收 1234 万元。" in text
    assert "华东最大" in text  # 要点

    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert table.cell(0, 0).text == "区域"
    assert table.cell(1, 1).text == "1234000"


# ── pdf ──────────────────────────────────────────


def test_render_pdf_is_a_pdf_with_text():
    from pypdf import PdfReader

    data = render_pdf("季度报告", SECTIONS, subtitle="内部资料")
    assert data.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 1
    # reportlab 的 CJK CID 字体（STSong-Light）能被 pypdf 抽回中文
    assert "本季度营收 1234 万元" in (reader.pages[0].extract_text() or "")


# ── 生成后自检（方案 C 的闭环） ─────────────────────


@pytest.mark.parametrize(
    ("data_fn", "filename", "needle"),
    [
        (lambda: render_xlsx(SHEETS), "报表.xlsx", "张三"),
        (lambda: render_docx("报告", SECTIONS), "报告.docx", "本季度营收"),
        (lambda: render_pdf("报告", SECTIONS), "报告.pdf", "本季度营收"),
    ],
)
def test_describe_for_verification_reads_back(data_fn, filename, needle):
    note = describe_for_verification(data_fn(), filename)
    assert note.startswith("回读校验")
    assert needle in note


# ── 产物通道 ─────────────────────────────────────


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    be = LocalBackend(tmp_path, url_prefix="/api/v1/files")
    monkeypatch.setattr(artifacts_mod, "get_backend", lambda: be)
    return be


def test_save_artifact_round_trip(backend):
    art = save_artifact(
        b"hello", filename="报表.xlsx", content_type="application/vnd.ms-excel", thread_id="u-1"
    )
    assert art.file_id and len(art.file_id) == 32
    assert art.url == f"/api/v1/files/{art.file_id}"  # 不带后缀，下载端点才认
    assert art.kind == "document"
    assert backend.get_bytes(f"{art.file_id}.xlsx") == b"hello"

    # 当轮回传：取走即清空
    assert [a.file_id for a in take_pending("u-1")] == [art.file_id]
    assert take_pending("u-1") == []

    # 跨轮持久化：日志里还在
    assert [a.file_id for a in load_thread_artifacts("u-1")] == [art.file_id]


def test_artifact_log_appends_and_isolates_threads(backend):
    a1 = save_artifact(b"1", filename="a.xlsx", content_type="x", thread_id="t1")
    a2 = save_artifact(b"2", filename="b.pdf", content_type="y", thread_id="t1")
    save_artifact(b"3", filename="c.docx", content_type="z", thread_id="t2")

    assert [a.file_id for a in load_thread_artifacts("t1")] == [a1.file_id, a2.file_id]
    assert len(load_thread_artifacts("t2")) == 1
    assert load_thread_artifacts("nope") == []


def test_artifact_thread_id_is_sanitized(backend):
    # thread_id 上游来自请求头里的 user_id，不能让 ../ 逃出存储根
    save_artifact(b"x", filename="a.txt", content_type="x", thread_id="../../evil")
    keys = list(backend.iter_keys())
    assert len(keys) == 2  # 产物 + 日志，都在根目录下
    assert all("/" not in k and ".." not in k for k in keys)


def test_artifact_without_thread_id_skips_log(backend):
    art = save_artifact(b"x", filename="a.txt", content_type="x")
    assert take_pending("") == []
    assert load_thread_artifacts("") == []
    assert backend.get_bytes(f"{art.file_id}.txt") == b"x"


def test_artifact_dataclass_round_trip():
    art = Artifact("a" * 32, "x.xlsx", 10, "application/x", "/u", "document")
    assert Artifact.from_dict(art.to_dict()) == art


def test_corrupt_log_is_tolerated(backend):
    backend.put_bytes("artifact-log-broken.json", b"{not json", content_type="application/json")
    assert load_thread_artifacts("broken") == []


# ── 工具层（模型看到的那两个工具） ───────────────────


def test_tool_render_spreadsheet_saves_and_returns_hint(backend):
    from core.report_tools import render_spreadsheet

    out = render_spreadsheet.invoke(
        {
            "filename": "2026Q3销售.xlsx",
            "sheets": [
                {"name": "Q3销售", "headers": ["区域", "销售额"], "rows": [["华东", 123.4]]}
            ],
        }
    )
    assert "已生成" in out
    assert "2026Q3销售.xlsx" in out
    assert "回读校验" in out  # 方案 C 的闭环：生成后回读自检
    assert "华东" in out
    assert "不要" in out  # 明确要求不要贴内容

    # 产物确实落库了
    files = list(backend.iter_keys())
    assert any(name.endswith(".xlsx") for name in files)


def test_tool_rejects_bad_filename(backend):
    from core.report_tools import render_document, render_spreadsheet

    bad_xlsx = render_spreadsheet.invoke(
        {"filename": "报表.csv", "sheets": [{"name": "S", "headers": ["A"], "rows": [[1]]}]}
    )
    assert "必须以 .xlsx 结尾" in bad_xlsx

    bad_doc = render_document.invoke(
        {"title": "T", "filename": "报告.txt", "sections": [{"paragraphs": ["x"]}]}
    )
    assert "必须以 .docx 或 .pdf" in bad_doc


def test_tool_rejects_empty_payload(backend):
    from core.report_tools import render_document, render_spreadsheet

    assert "不能为空" in render_spreadsheet.invoke({"filename": "a.xlsx", "sheets": []})
    assert "不能为空" in render_document.invoke(
        {"title": "T", "filename": "a.docx", "sections": []}
    )


@pytest.mark.parametrize("filename", ["季度报告.docx", "季度报告.pdf"])
def test_tool_render_document_by_extension(backend, filename):
    from core.report_tools import render_document

    out = render_document.invoke(
        {
            "title": "季度报告",
            "filename": filename,
            "sections": [{"heading": "一、概览", "paragraphs": ["本季度营收 1234 万元。"]}],
        }
    )
    assert "已生成" in out
    assert filename in out
    assert "本季度营收" in out  # 回读校验确实读到了内容
    assert any(name.endswith(filename.rsplit(".", 1)[-1]) for name in backend.iter_keys())
