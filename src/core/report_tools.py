"""给模型用的报表生成工具（方案 C 的 A 路线）。

模型只产出**结构化 spec**，渲染在服务端完成（:mod:`core.reports`），产物写进
存储并回传给前端下载，同时同步到调用用户的持久沙箱供后续编辑。

**与沙箱路线（run_python）的分工**：

* 这里 —— 表格/文档类的常规报表：确定性、无冷启动、直接给下载链接；
* 沙箱 —— 需要画图（matplotlib）、要跑大计算、要对一堆明细文件做处理的场景。

两条路线产出的都是同一种产物（:mod:`core.artifacts`），所以前端只有一个
下载卡片，不需要区分。
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Annotated, Any, Final

from langchain.tools import tool
from langchain_core.tools import ToolException
from langgraph.config import get_config
from pydantic import BaseModel, ConfigDict, Field

from core.artifacts import save_artifact
from core.context_type import get_runtime_context
from core.reports import (
    SectionSpec,
    SheetSpec,
    TableSpec,
    describe_for_verification,
    render_docx,
    render_pdf,
    render_xlsx,
)
from core.sandbox.artifacts import artifact_path, sync_artifact
from core.sandbox.file_links import sandbox_file_url
from core.sandbox.files import SandboxFileError
from core.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["REPORT_TOOLS", "render_document", "render_document_from_files", "render_spreadsheet"]

_MIME: Final[dict[str, str]] = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}

#: 一次最多几张工作表 / 几个章节 —— 防模型一口气塞几百页
_MAX_SHEETS: Final = 10
_MAX_SECTIONS: Final = 60


# ── 工具入参（pydantic → 模型可见 schema） ──────────


class ReportTable(BaseModel):
    """一张表格。"""

    headers: list[str] = Field(description="表头（第一行），每列一个")
    rows: list[list[Any]] = Field(
        default_factory=list,
        description="数据行；每个元素是这一行的各列值。字符串以 = 开头会写成 Excel 公式",
    )
    title: str | None = Field(default=None, description="表格上方的大标题，可省略")


class ReportSheet(BaseModel):
    """Excel 的一个工作表（一个工作表放一张表）。"""

    name: str = Field(description="工作表名，例如「销售明细」")
    headers: list[str] = Field(description="表头（第一行）")
    rows: list[list[Any]] = Field(default_factory=list, description="数据行")
    title: str | None = Field(default=None, description="表上方的大标题，可省略")


class ReportSection(BaseModel):
    """文档的一个章节。"""

    heading: str | None = Field(default=None, description="章节标题，可省略")
    paragraphs: list[str] = Field(default_factory=list, description="正文段落")
    bullets: list[str] = Field(default_factory=list, description="要点（无序列表）")
    table: ReportTable | None = Field(default=None, description="这一节附带的表格，可省略")


# ── 工具 ────────────────────────────────────────


@tool
def render_spreadsheet(
    filename: str, sheets: list[ReportSheet], sandbox_dir: str | None = None
) -> str:
    """把结构化数据渲染成一个 Excel（.xlsx）文件，用户可以直接下载。

    适合：数据汇总、名单、对比表、带公式的计算表。
    不适合：需要画图（折线/柱状）或要跑复杂计算 —— 那些用 run_python 在沙箱里做完再来调本工具。

    Args:
        filename: 文件名，必须以 .xlsx 结尾，例如「2026-09 销售月报.xlsx」。
        sheets: 工作表列表，每个工作表一张表；表头放 headers，数据放 rows。
        sandbox_dir: 用户沙箱内目标目录，例如 /workspace/学生管理；省略则使用独立产物目录。
    """
    if not filename.lower().endswith(".xlsx"):
        return _error("文件名必须以 .xlsx 结尾，请修正后重试。")
    if not sheets:
        return _error("sheets 不能为空，至少要有一个工作表。")

    try:
        data = render_xlsx(
            [
                SheetSpec(
                    name=sheet.name,
                    table=TableSpec(
                        headers=list(sheet.headers),
                        rows=[list(row) for row in sheet.rows],
                        title=sheet.title,
                    ),
                )
                for sheet in sheets[:_MAX_SHEETS]
            ]
        )
    except Exception as exc:
        logger.exception("report.xlsx.failed", filename=filename)
        return _error(f"生成 Excel 失败：{exc}。请检查数据格式后重试。")

    row_count = sum(len(sheet.rows) for sheet in sheets[:_MAX_SHEETS])
    return _finish(data, filename, f"{len(sheets)} 个工作表 / 共 {row_count} 行", sandbox_dir)


@tool
def render_document(
    title: str,
    filename: str,
    sections: list[ReportSection],
    subtitle: str = "",
    sandbox_dir: str | None = None,
) -> str:
    """把章节结构渲染成 Word（.docx）或 PDF 报告，用户可以直接下载。

    **格式由 filename 的后缀决定**：``.docx`` 生成 Word，``.pdf`` 生成 PDF。
    适合：分析报告、总结、说明文档（带小标题、正文、要点、表格）。
    不适合：需要图表 —— 那些用 run_python 在沙箱里出图后在正文里引用。
    只接受直接提供的 sections。已有章节文件时必须使用 render_document_from_files。
    返回 JSON：state=success 才表示成功；state=error 时查看 error，不能宣称已完成。
    sandbox_dir 省略即可，不要填写空字符串或相对路径。

    Args:
        title: 文档主标题。
        filename: 文件名，必须以 .docx 或 .pdf 结尾，例如「2026 Q3 季度报告.pdf」。
        sections: 章节列表，按顺序渲染。
        subtitle: 副标题（可省略），常用来放日期或"内部资料"。
    """
    return _render_document(title, filename, sections, subtitle, sandbox_dir)


class FileDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, description="文档标题")
    filename: str = Field(min_length=1, description="仅文件名，例如 报告.docx 或 报告.pdf")
    source_files: list[Annotated[str, Field(min_length=1, max_length=1024)]] = Field(
        min_length=1, max_length=60, description="按章节顺序列出的会话内 UTF-8 .txt 相对路径，必填"
    )


@tool(args_schema=FileDocumentInput)
def render_document_from_files(
    title: str,
    filename: str,
    source_files: Annotated[list[str], Field(min_length=1, max_length=60)],
) -> str:
    """将已经保存的章节文件合并成可下载的 Word 或 PDF，正文不会重新经过模型。

    title 是文档标题；filename 只填文件名，例如 报告.docx 或 报告.pdf，不含目录。
    source_files 必填，按章节顺序列出当前会话的 UTF-8 .txt 相对路径，
    例如 ["dissertation/01-绪论.txt", "dissertation/02-设计.txt"]。
    每个文件一个章节、文件名为章节标题、空行分段，总计最多 4 MiB。
    不需要 sections、subtitle 或 sandbox_dir；输出自动保存在当前会话产物目录。
    只在章节内容全部保存或用户要求阶段交付时调用一次，不要每新增几段就渲染。
    返回 JSON：state=success 表示生成成功，data 包含文件回执；state=error 表示失败，
    根据 error 修正参数或文件，不要用相同错误参数反复重试，也不要重写已有正文。
    """
    if PurePosixPath(filename).suffix.lower() not in {".docx", ".pdf"}:
        return _error("文件名必须以 .docx 或 .pdf 结尾。")
    try:
        artifact_path(filename, "pending")
    except ValueError as exc:
        return _error(f"文件路径不合法：{exc}。")
    try:
        sections = _sections_from_files(source_files)
    except (ToolException, SandboxFileError, OSError, OverflowError) as exc:
        logger.exception("report.sources.failed")
        return _error(
            f"读取章节文件失败：{exc}。请修正 source_files 或文件，不要重新生成全部正文。"
        )
    return _render_document(title, filename, sections)


def _render_document(
    title: str,
    filename: str,
    sections: list[ReportSection],
    subtitle: str = "",
    sandbox_dir: str | None = None,
) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"docx", "pdf"}:
        return _error("文件名必须以 .docx 或 .pdf 结尾，请修正后重试。")
    if not sections:
        return _error(
            "sections 不能为空。若正文已保存在文件中，请改用 render_document_from_files 并提供 source_files。"
        )
    if len(sections) > _MAX_SECTIONS:
        return _error(f"章节数超过 {_MAX_SECTIONS}，请分卷生成；没有截断或生成文件。")
    try:
        artifact_path(filename, "pending", sandbox_dir)
    except ValueError as exc:
        return _error(f"文件路径不合法：{exc}。请省略 sandbox_dir 使用默认目录。")

    specs = [
        SectionSpec(
            heading=section.heading,
            paragraphs=list(section.paragraphs),
            bullets=list(section.bullets),
            table=(
                TableSpec(
                    headers=list(section.table.headers),
                    rows=[list(row) for row in section.table.rows],
                    title=section.table.title,
                )
                if section.table is not None
                else None
            ),
        )
        for section in sections[:_MAX_SECTIONS]
    ]

    try:
        data = (
            render_docx(title, specs, subtitle=subtitle)
            if suffix == "docx"
            else render_pdf(title, specs, subtitle=subtitle)
        )
    except Exception as exc:
        logger.exception("report.document.failed", filename=filename, suffix=suffix)
        return _error(f"生成文档失败：{exc}。请检查内容格式后重试。")

    chars = sum(
        len("".join(paragraph.split())) for section in sections for paragraph in section.paragraphs
    )
    return _finish(
        data,
        filename,
        f"{len(specs)} 个章节 / 正文段落 {chars} 个非空白字符（不含标题、表格、要点）",
        sandbox_dir,
    )


def _sections_from_files(paths: list[str]) -> list[ReportSection]:
    from core.sandbox.files import read_session_files

    ctx = get_runtime_context()
    if ctx is None:
        raise RuntimeError("缺少用户上下文")
    thread = str(ctx.extra.get("approval_thread_id", ""))
    if len(paths) > _MAX_SECTIONS or len(set(paths)) != len(paths):
        raise ToolException("章节文件不能重复，且最多 60 个")
    sections = []
    for path in paths:
        if PurePosixPath(path).suffix.lower() != ".txt":
            raise ToolException("章节文件必须是 UTF-8 .txt 文本")
    for path, content in zip(
        paths, read_session_files(ctx, thread, paths, max_bytes=4 * 1024 * 1024), strict=True
    ):
        try:
            text = content.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise ToolException(f"章节文件不是 UTF-8 文本：{path}") from exc
        if not text:
            raise ToolException(f"章节文件为空：{path}")
        sections.append(
            ReportSection(
                heading=PurePosixPath(path).stem,
                paragraphs=[
                    p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()
                ],
            )
        )
    return sections


# ── 内部 ────────────────────────────────────────


def _error(message: str) -> str:
    # ToolMessage 的 content 本就是 JSON 文本；保留字符串契约并让流式/历史统一识别 state。
    return json.dumps({"state": "error", "data": None, "error": message}, ensure_ascii=False)


def _finish(data: bytes, filename: str, summary: str, sandbox_dir: str | None = None) -> str:
    """落库 + 回读自检 + 给模型的回执。"""
    suffix = filename.rsplit(".", 1)[-1].lower()
    try:
        artifact_path(filename, "pending", sandbox_dir)
    except ValueError as exc:
        return _error(f"文件路径不合法：{exc}。请修正后重试。")
    try:
        artifact = save_artifact(
            data,
            filename=filename,
            content_type=_MIME.get(suffix, "application/octet-stream"),
            thread_id=_thread_id(),
        )
    except Exception as exc:
        logger.exception("report.save.failed", filename=filename)
        return _error(f"文件已渲染但保存失败：{exc}。请告诉用户稍后重试。")

    sandbox_path = artifact_path(filename, artifact.file_id, sandbox_dir)
    sync_error = ""
    try:
        sandbox_path = sync_artifact(data, sandbox_path)
        location = f"已同步到当前用户沙箱：{sandbox_path}。后续用 run_python 编辑此文件。"
        ctx = get_runtime_context()
        if ctx and ctx.extra.get("approval_thread_id"):
            url = sandbox_file_url(str(ctx.extra["approval_thread_id"]), sandbox_path)
            label = filename.replace("[", "\\[").replace("]", "\\]")
            location += f"\n请在回复中提供链接：[{label}]({url}) · [下载]({url}&download=true)"
    except Exception:
        logger.exception("report.sandbox.sync.failed", file_id=artifact.file_id)
        location = "下载副本已保存，但同步到用户沙箱失败，不能宣称已在沙箱中创建目录或文件，请告知用户并重试。"
        sync_error = "文件下载副本已保存，但沙箱同步失败；保留已有文件，不要重复生成正文。"
    verify = describe_for_verification(data, filename)
    message = (
        f"已生成《{filename}》（{_human_size(len(data))}，{summary}），"
        f"用户会在消息里看到下载卡片。\n"
        f"{verify}\n"
        f"{location}\n"
        "下载卡片是生成时的副本，沙箱内后续编辑不会自动更新下载副本。\n"
        f"（file_id={artifact.file_id}，仅供系统内部引用，不要去读它）\n"
        "请用一两句话告诉用户文件已生成、里面有什么，**不要**把文件内容贴进回复。"
    )
    return json.dumps(
        {
            "state": "error" if sync_error else "success",
            "data": {
                "message": message,
                "file_id": artifact.file_id,
                "filename": filename,
                "size": len(data),
                "url": artifact.url,
                "sandbox_path": None if sync_error else sandbox_path,
            },
            "error": sync_error,
        },
        ensure_ascii=False,
    )


def _thread_id() -> str | None:
    """从 LangGraph 运行时配置里取 thread_id，供产物回传/持久化用。"""
    try:
        config = get_config()
    except Exception:
        return None
    configurable = (config or {}).get("configurable") or {}
    thread_id = configurable.get("thread_id")
    return str(thread_id) if thread_id else None


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


#: 主 agent 注册用
REPORT_TOOLS: tuple[Any, ...] = (render_spreadsheet, render_document, render_document_from_files)
