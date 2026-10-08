"""``core.documents`` 的解析与校验测试。

覆盖：魔数识别、加密/扫描件等降级、以及三类文档的正文抽取。
测试用的 docx / xlsx 都是现造的（内存里生成，不依赖外部文件）。
"""

from __future__ import annotations

import io

import pytest

from core.documents import (
    MAX_DOC_BYTES,  # noqa: F401  (导入即验证常量存在)
    DetectedFormat,
    DocumentError,
    detect_format,
    document_block,
    extract_text,
    is_image_suffix,
    mime_for_suffix,
)

PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF_HEAD = b"%PDF-1.4\n" + b"\x00" * 32
ZIP_HEAD = b"PK\x03\x04" + b"\x00" * 32
CFB_HEAD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32


# ── 格式识别 ──────────────────────────────────────


def test_detect_image_ignores_wrong_extension():
    # 改扩展名也拦不住：图片按魔数认
    assert detect_format(PNG_HEAD, "其实是图.txt").kind == "image"
    assert detect_format(PNG_HEAD, "其实是图.txt").suffix == "png"


def test_detect_pdf():
    fmt = detect_format(PDF_HEAD, "报告.pdf")
    assert (fmt.kind, fmt.suffix, fmt.mime) == ("pdf", "pdf", "application/pdf")


def test_detect_ooxml_by_extension():
    assert detect_format(ZIP_HEAD, "表格.xlsx").kind == "xlsx"
    assert detect_format(ZIP_HEAD, "文档.docx").kind == "docx"


def test_detect_text_types():
    assert detect_format(b"a,b,c\n1,2,3", "名单.csv").kind == "text"


def test_reject_legacy_office():
    with pytest.raises(DocumentError, match="旧版"):
        detect_format(CFB_HEAD, "老表格.xls")


def test_reject_unknown_type():
    with pytest.raises(DocumentError, match="不支持的文件类型"):
        detect_format(b"MZ\x90\x00", "程序.exe")


def test_reject_zip_without_office_extension():
    with pytest.raises(DocumentError, match="Office 压缩包"):
        detect_format(ZIP_HEAD, "压缩包.zip")


def test_html_disguised_as_xlsx_is_taken_as_text():
    # 教务 / ERP 系统"导出 Excel"经常就是这么干的
    html = "<!DOCTYPE html><html><table><tr><td>张三</td></tr></table></html>".encode()
    fmt = detect_format(html, "班级名单表.xlsx")
    assert fmt.kind == "text"
    out = extract_text(html, fmt)
    assert "张三" in out.text


def test_gbk_csv_disguised_as_xlsx():
    csv = "姓名,分数\n张三,91\n".encode("gbk")
    assert detect_format(csv, "名单.xlsx").kind == "text"


def test_binary_disguised_as_xlsx_gets_a_clear_error():
    blob = b"\x00\x01\x02\x03" + bytes(range(64))
    with pytest.raises(DocumentError, match=r"内容不是真正的 XLSX"):
        detect_format(blob, "假表格.xlsx")


def test_suffix_helpers():
    assert is_image_suffix("PNG")
    assert not is_image_suffix("pdf")
    assert mime_for_suffix("xlsx").endswith("spreadsheetml.sheet")


# ── 抽取 ──────────────────────────────────────────


def _make_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph("季度总结：营收 1234 万元")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "区域"
    table.cell(0, 1).text = "销量"
    table.cell(1, 0).text = "华东"
    table.cell(1, 1).text = "88"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_xlsx() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "名单"
    ws.append(["姓名", "分数"])
    ws.append(["张三", 91])
    ws.append(["李四", 78])
    ws2 = wb.create_sheet("备注")
    ws2.append(["这一页也要能读到"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_docx():
    data = _make_docx()
    fmt = detect_format(data[:512], "总结.docx")
    out = extract_text(data, fmt)
    assert "营收 1234 万元" in out.text
    assert "华东" in out.text  # 表格内容也要抽出来
    assert out.kind == "docx"
    assert not out.truncated


def test_extract_xlsx_reads_all_sheets_and_values():
    data = _make_xlsx()
    fmt = detect_format(data[:512], "名单.xlsx")
    out = extract_text(data, fmt)
    assert "名单" in out.text and "备注" in out.text
    assert "张三" in out.text and "91" in out.text
    assert "这一页也要能读到" in out.text
    assert "2 个工作表" in out.detail


def test_extract_plain_text_gbk():
    data = "姓名,分数\n张三,91\n".encode("gbk")
    fmt = detect_format(data[:512], "名单.csv")
    out = extract_text(data, fmt)
    assert "张三" in out.text


def test_truncation_is_reported():
    data = ("x" * 5000).encode()
    fmt = DetectedFormat(kind="text", suffix="txt", mime="text/plain")
    out = extract_text(data, fmt, max_chars=100)
    assert out.truncated is True
    assert len(out.text) == 100


def test_document_block_mentions_filename_and_truncation():
    fmt = DetectedFormat(kind="text", suffix="txt", mime="text/plain")
    out = extract_text(b"hello", fmt)
    block = document_block(out, "说明.txt")
    assert "说明.txt" in block
    assert "hello" in block

    long_out = extract_text(("y" * 500).encode(), fmt, max_chars=10)
    assert "已截断" in document_block(long_out, "长文.txt")


def test_broken_docx_raises_readable_error():
    fmt = DetectedFormat(kind="docx", suffix="docx", mime="application/msword")
    with pytest.raises(DocumentError, match=r"解析失败|Word"):
        extract_text(b"PK\x03\x04" + "这不是真的 docx".encode(), fmt)
