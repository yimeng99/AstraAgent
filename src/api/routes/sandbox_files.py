"""当前会话的沙箱文件浏览与管理；所有路径均限制在会话根目录内。"""

from __future__ import annotations

import io
import mimetypes
import zipfile
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from api.deps import current_context
from api.responses import ApiResult, success
from core.context_type import MemoryContext
from core.documents import detect_format, extract_text
from core.sandbox.files import SandboxFileError, operate_file
from core.sandbox.service import SandboxBusyError
from core.sessions import ThreadAccessError, assert_thread_owner
from core.utils.logging import get_logger

router = APIRouter(prefix="/threads/{thread_id}/sandbox")
logger = get_logger("api.sandbox_files")
_LIMIT = 20 * 1024 * 1024
Context = Annotated[MemoryContext, Depends(current_context)]


class FileChange(BaseModel):
    path: str = ""
    name: str


def _relative(path: str) -> str:
    if (
        path.startswith("/")
        or ".." in PurePosixPath(path).parts
        or any(char in path for char in ("\\", "\0"))
    ):
        raise HTTPException(400, "请使用当前会话内的相对路径")
    normalized = str(PurePosixPath(path)) if path else ""
    return "" if normalized == "." else normalized


def _name(name: str) -> str:
    if (
        not name
        or name in (".", "..")
        or len(name) > 255
        or any(char in name for char in ("/", "\\", "\0", "\r", "\n"))
    ):
        raise HTTPException(400, "文件名称不合法")
    return name


def _operate(
    ctx: MemoryContext,
    thread: str,
    action: str,
    path: str,
    *,
    destination: str = "",
    data: bytes | None = None,
):
    try:
        assert_thread_owner(thread, ctx.user_id)
    except ThreadAccessError:
        raise HTTPException(404, "对话不存在") from None
    if ctx.user_id == "anonymous" or not ctx.can("read"):
        raise HTTPException(403, "当前用户无法访问工作空间")
    path, destination = _relative(path), _relative(destination)
    try:
        return operate_file(ctx, thread, action, path, destination=destination, data=data)
    except SandboxFileError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except OverflowError:
        raise HTTPException(413, "文件超过 20 MiB") from None
    except SandboxBusyError:
        raise HTTPException(
            409, "沙箱正在执行任务，请稍后刷新", headers={"Retry-After": "2"}
        ) from None
    except Exception:
        logger.exception("sandbox.files.failed", thread_id=thread, action=action)
        raise HTTPException(503, "沙箱文件服务暂不可用，请稍后重试") from None


@router.get("/files", response_model=ApiResult[object])
def list_files(thread_id: str, ctx: Context):
    return success(_operate(ctx, thread_id, "list", ""))


@router.get("/content")
def file_content(thread_id: str, ctx: Context, path: str, download: bool = False):
    data = _operate(ctx, thread_id, "read", path)
    # 活动内容按附件输出，不能以本站源运行用户生成的 HTML/SVG/JS。
    suffix = PurePosixPath(path).suffix.lower()
    safe_inline = suffix in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
    disposition = "inline" if safe_inline and not download else "attachment"
    return Response(
        data,
        media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(PurePosixPath(path).name)}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/preview", response_model=ApiResult[object])
def preview_document(thread_id: str, ctx: Context, path: str):
    if PurePosixPath(path).suffix.lower() != ".docx":
        raise HTTPException(415, "当前仅支持 Word 正文预览")
    data = _operate(ctx, thread_id, "read", path)
    try:
        # 文件大小限制不能防止 ZIP 炸弹，还需限制解压后的总大小。
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                raise HTTPException(413, "文档解压后过大")
        text = extract_text(data, detect_format(data, path), max_chars=50000)
        return success({"text": text.text})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "文档损坏或不支持预览") from None


@router.post("/files", response_model=ApiResult[object])
async def upload_file(
    thread_id: str, ctx: Context, file: Annotated[UploadFile, File()], path: str = ""
):
    data = await file.read(_LIMIT + 1)
    if len(data) > _LIMIT:
        raise HTTPException(413, "文件超过 20 MiB")
    target = str(PurePosixPath(_relative(path)) / _name(file.filename or "upload"))
    return success(await run_in_threadpool(_operate, ctx, thread_id, "upload", target, data=data))


@router.post("/directories", response_model=ApiResult[object])
def create_directory(thread_id: str, ctx: Context, body: FileChange):
    target = str(PurePosixPath(_relative(body.path)) / _name(body.name))
    return success(_operate(ctx, thread_id, "mkdir", target))


@router.patch("/files", response_model=ApiResult[object])
def rename_file(thread_id: str, ctx: Context, body: FileChange):
    path = _relative(body.path)
    destination = str(PurePosixPath(path).parent / _name(body.name))
    return success(_operate(ctx, thread_id, "rename", path, destination=destination))


@router.delete("/files", response_model=ApiResult[object])
def delete_file(thread_id: str, ctx: Context, path: str):
    return success(_operate(ctx, thread_id, "delete", path))
