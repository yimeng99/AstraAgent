"""报表渲染：结构化 spec → xlsx / docx / pdf。

这是「方案 C」里的 **A 路线**：模型只产出**结构化数据**，渲染在服务端做。

**为什么不让模型直接写 python-docx / openpyxl 代码**：

* 表头样式、数字格式、列宽、冻结窗格这些"能直接发出去"的细节，模型每次写的
  都不一样，还得为跑通代码烧 token 和重试；
* 结构化 spec 可校验、可回归测试、后续可以换成**模板**（docxtpl / 模板 xlsx）
  而不用改工具协议；
* 不依赖沙箱：没有冷启动、没有 600s TTL、没有"一个用户一个沙箱"的并发上限。

要画图 / 要跑大计算，走沙箱那条线（:mod:`core.report_tools` 里的说明）。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Final

from core.documents import DocumentError, detect_format, extract_text
from core.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "SectionSpec",
    "SheetSpec",
    "TableSpec",
    "describe_for_verification",
    "render_docx",
    "render_pdf",
    "render_xlsx",
]

#: 单元格最多写多少字符（防止模型把整段文章塞进一个格子）
_MAX_CELL_CHARS: Final = 2000
#: 单表最多写多少行（防御性上限，正常报表远小于它）
_MAX_ROWS: Final = 5000
#: 列宽上下限（字符数）
_MIN_COL_WIDTH: Final = 8
_MAX_COL_WIDTH: Final = 48


@dataclass(frozen=True, slots=True)
class TableSpec:
    """一张表。"""

    headers: list[str]
    rows: list[list[Any]]
    title: str | None = None


@dataclass(frozen=True, slots=True)
class SheetSpec:
    """xlsx 的一个工作表（一个 sheet 一张表）。"""

    name: str
    table: TableSpec


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """文档的一个章节（docx / pdf 共用）。"""

    heading: str | None = None
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    table: TableSpec | None = None


# ── 公共小工具 ────────────────────────────────────


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[:_MAX_CELL_CHARS]


def _is_formula(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("=")


#: Excel 工作表名的非法字符
_BAD_SHEET_CHARS: Final = set("[]:*?/\\")


def _safe_sheet_name(name: str, index: int) -> str:
    """Excel 工作表名限制：≤31 字符、不含 ``[]:*?/\\``。"""
    cleaned = "".join(ch for ch in (name or "").strip() if ch not in _BAD_SHEET_CHARS)
    return (cleaned or f"Sheet{index}")[:31]


# ── xlsx ─────────────────────────────────────────


def render_xlsx(sheets: list[SheetSpec]) -> bytes:
    """把若干工作表渲染成 .xlsx。

    做得比"能打开"多一点，因为报表是给人看的：表头加粗带底色、冻结首行、
    自动筛选、列宽按内容自适应、数字带千分位。

    Args:
        sheets: 工作表列表（至少一个）。

    Returns:
        xlsx 字节。

    Raises:
        ValueError: 没有工作表。
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    if not sheets:
        raise ValueError("至少需要一个工作表")

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)  # 去掉默认空表，避免多出一页白板

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4472C4")
    title_font = Font(bold=True, size=14)
    wrap_top = Alignment(vertical="top", wrap_text=False)

    for index, sheet in enumerate(sheets, start=1):
        ws = workbook.create_sheet(_safe_sheet_name(sheet.name, index))
        table = sheet.table
        headers = [_cell_text(h) for h in table.headers]
        width = max(1, len(headers))
        row_cursor = 1

        if table.title:
            ws.cell(row=1, column=1, value=table.title).font = title_font
            if width > 1:
                ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
            row_cursor = 2

        for col, head in enumerate(headers, start=1):
            cell = ws.cell(row=row_cursor, column=col, value=head)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        header_row = row_cursor

        for row_offset, row in enumerate(table.rows[:_MAX_ROWS], start=1):
            for col, value in enumerate(row[:width], start=1):
                if _is_formula(value):
                    ws.cell(row=header_row + row_offset, column=col, value=str(value))
                    continue
                if isinstance(value, bool) or value is None:
                    cell = ws.cell(row=header_row + row_offset, column=col, value=value)
                elif isinstance(value, int):
                    cell = ws.cell(row=header_row + row_offset, column=col, value=value)
                    cell.number_format = "#,##0"
                elif isinstance(value, float):
                    cell = ws.cell(row=header_row + row_offset, column=col, value=value)
                    cell.number_format = "#,##0.00"
                else:
                    cell = ws.cell(row=header_row + row_offset, column=col, value=_cell_text(value))
                cell.alignment = wrap_top

        last_row = header_row + min(len(table.rows), _MAX_ROWS)
        if headers:
            ws.auto_filter.ref = f"A{header_row}:{get_column_letter(width)}{last_row}"
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

        # 列宽：按内容估个大概，限制在上下限内
        for col in range(1, width + 1):
            longest = len(headers[col - 1]) if col <= len(headers) else 0
            for row in table.rows[:200]:
                if col <= len(row):
                    longest = max(longest, len(_cell_text(row[col - 1])))
            ws.column_dimensions[get_column_letter(col)].width = min(
                _MAX_COL_WIDTH, max(_MIN_COL_WIDTH, longest + 4)
            )

    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


# ── docx ─────────────────────────────────────────


def _set_cjk_font(document: Any) -> None:
    """把正文默认字体设成中英混排友好的字体。

    python-docx 默认模板是 Calibri，中文会走回退字体；显式设 eastAsia 之后
    Word 里打开才是统一字体。
    """
    from docx.oxml.ns import qn

    normal = document.styles["Normal"]
    normal.font.name = "微软雅黑"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")


def render_docx(title: str, sections: list[SectionSpec], *, subtitle: str = "") -> bytes:
    """把章节结构渲染成 .docx。"""
    from docx import Document
    from docx.shared import Pt

    document = Document()
    _set_cjk_font(document)

    document.add_heading(title or "报告", level=0)
    if subtitle:
        para = document.add_paragraph(subtitle)
        para.runs[0].font.size = Pt(10)

    for section in sections:
        if section.heading:
            document.add_heading(section.heading, level=1)
        for text in section.paragraphs:
            document.add_paragraph(text)
        for bullet in section.bullets:
            document.add_paragraph(bullet, style="List Bullet")
        if section.table is not None:
            _add_docx_table(document, section.table)

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _add_docx_table(document: Any, table: TableSpec) -> None:
    headers = [_cell_text(h) for h in table.headers]
    if table.title:
        document.add_paragraph(table.title).runs[0].bold = True
    if not headers:
        return

    table_obj = document.add_table(rows=1, cols=len(headers))
    table_obj.style = "Table Grid"
    for col, head in enumerate(headers):
        cell = table_obj.rows[0].cells[col]
        cell.text = head
        for run in cell.paragraphs[0].runs:
            run.bold = True

    for row in table.rows[:_MAX_ROWS]:
        cells = table_obj.add_row().cells
        for col in range(len(headers)):
            cells[col].text = _cell_text(row[col]) if col < len(row) else ""


# ── pdf ──────────────────────────────────────────


def _pdf_font() -> str:
    """注册并返回一个带中文的字体名。

    reportlab 自带 Adobe 的 CJK CID 字体（STSong-Light），不用额外塞 ttf 文件，
    在 Windows / Linux 上都一样。
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    name = "STSong-Light"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(name))
    return name


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_pdf(title: str, sections: list[SectionSpec], *, subtitle: str = "") -> bytes:
    """把章节结构渲染成 .pdf（reportlab Platypus）。

    注意 Platypus 的 ``Paragraph`` 是**按 XML 解析文本**的，用户内容里的
    ``&`` / ``<`` 会让 build 直接抛错 —— 所以下面每一处文本都过 ``_xml_escape``，
    新增段落时别漏。
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font = _pdf_font()
    body = ParagraphStyle("body", fontName=font, fontSize=10.5, leading=16)
    heading = ParagraphStyle("heading", fontName=font, fontSize=14, leading=20, spaceBefore=10)
    title_style = ParagraphStyle("title", fontName=font, fontSize=20, leading=26, spaceAfter=6)
    sub_style = ParagraphStyle("sub", fontName=font, fontSize=10, textColor=colors.grey)

    story: list[Any] = [Paragraph(_xml_escape(title or "报告"), title_style)]
    if subtitle:
        story.append(Paragraph(_xml_escape(subtitle), sub_style))
    story.append(Spacer(1, 6 * mm))

    for section in sections:
        if section.heading:
            story.append(Paragraph(_xml_escape(section.heading), heading))
        for text in section.paragraphs:
            story.append(Paragraph(_xml_escape(text), body))
        for bullet in section.bullets:
            story.append(Paragraph("• " + _xml_escape(bullet), body))
        if section.table is not None:
            story.append(Spacer(1, 2 * mm))
            story.append(_pdf_table(section.table))
            story.append(Spacer(1, 2 * mm))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title or "报告",
    )
    doc.build(story)
    return buf.getvalue()


def _pdf_table(table: TableSpec) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    header_style = ParagraphStyle("th", fontName=_pdf_font(), fontSize=9.5, leading=13)
    cell_style = ParagraphStyle("td", fontName=_pdf_font(), fontSize=9.5, leading=13)

    headers = [_cell_text(h) for h in table.headers]
    data: list[list[Any]] = [[Paragraph(_xml_escape(h), header_style) for h in headers]]
    for row in table.rows[:200]:  # PDF 里长表意义不大，截断避免翻几十页
        data.append(
            [
                Paragraph(_xml_escape(_cell_text(row[col]) if col < len(row) else ""), cell_style)
                for col in range(len(headers))
            ]
        )

    # repeatRows=1：表格跨页时自动重复表头，否则第二页起没有列名
    obj = Table(data, repeatRows=1, hAlign="LEFT")
    obj.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B7C3")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return obj


# ── 生成后自检（方案 C 的闭环） ─────────────────────


def describe_for_verification(data: bytes, filename: str) -> str:
    """生成后立刻用**同一套 ingest 管线**回读一遍。

    这是方案 C 里"产物回读自检"那一步：让模型拿到一句可核对的事实
    （几个 sheet / 多少行 / 开头内容），而不是只回一句"已生成"。

    回读失败不算错误 —— 文件已经落库，用户能下载，只是模型少了个抓手。
    """
    try:
        fmt = detect_format(data[:512], filename)
        extracted = extract_text(data, fmt, max_chars=400)
    except DocumentError as exc:
        return f"（回读校验不可用：{exc}）"
    except Exception:
        logger.exception("report.verify.failed", filename=filename)
        return "（回读校验不可用）"

    head = " / ".join(line for line in extracted.text.splitlines() if line.strip())[:160]
    if not head:
        return f"回读校验：{extracted.detail or fmt.kind}（未能抽取文字，不影响下载）"
    detail = f"（{extracted.detail}）" if extracted.detail else ""
    return f"回读校验{detail}：{head}"
