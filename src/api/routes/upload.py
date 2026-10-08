"""文件上传端点。

``POST /api/v1/upload`` —— multipart/form-data，字段名 ``file``。

上传只做「校验 + 存储 + 回执」，不解析内容。图片如何进入 LLM 由
:mod:`api.routes.chat` 决定（多模态或工具读取）。

存储落点由 :mod:`core.storage` 决定：

* **local** —— 落 ``workspace/uploads``，预览走本端点 ``/files/{id}``
* **oss**   —— 写阿里云 OSS，回执直接给**签名 URL**；``/files/{id}`` 仍可用
  （后端代理下载），但前端应优先用回执里的签名 URL，少一跳。

回执里的 ``preview_url`` 已经是**可直接使用**的地址，前端不需要再拼。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse, Response

from api.deps import current_user_id
from api.responses import ApiResult, success
from api.schemas.upload import UploadResponse
from api.storage import (
    UploadRejectedError,
    load_stored_bytes,
    resolve_and_presign,
    store_upload,
)
from core.documents import mime_for_suffix
from core.storage import StorageError, get_backend
from core.utils.logging import get_logger

logger = get_logger("api.upload")

router = APIRouter()

#: 请求体硬上限（含 multipart 开销）。比单文件上限（文档 20 MiB）略宽。
_REQUEST_BUDGET = 24 * 1024 * 1024


def _storage_error(exc: StorageError, *, user_id: str, file_id: str = "") -> HTTPException:
    """把存储后端故障转成 5xx，并记 exception 日志。

    与用户输入问题（4xx）分开：OSS 超时/凭证错是运维问题，返 4xx 会误导
    前端以为是用户传错了。
    """
    logger.exception("storage.failed", user_id=user_id, file_id=file_id, error=str(exc))
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="文件存储暂时不可用，请稍后重试",
    )


@router.post("/upload", response_model=ApiResult[UploadResponse])
async def upload_file(
    file: Annotated[UploadFile, File(description="待上传的图片")],
    user_id: Annotated[str, Depends(current_user_id)],
) -> ApiResult[UploadResponse]:
    """上传一张图片，返回可回传的 ``file_id``。

    前端拿到回执后，在 ``/chat/stream`` 的 ``attachments`` 里带上
    ``file_id`` 即可；不要在前端自行拼服务端路径。
    """
    # Content-Length 粗筛：超预算直接拒，避免把超大请求体读进内存
    if file.size is not None and file.size > _REQUEST_BUDGET:
        logger.warning("upload.rejected.too_large", size=file.size, user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="文件过大",
        )

    try:
        stored = await store_upload(
            file,
            filename=file.filename or "upload",
            content_type=file.content_type or "",
        )
    except UploadRejectedError as exc:
        logger.warning("upload.rejected", reason=str(exc), user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except StorageError as exc:
        raise _storage_error(exc, user_id=user_id) from exc

    return success(
        UploadResponse(
            file_id=stored.file_id,
            filename=stored.filename,
            content_type=stored.content_type,
            size=stored.size,
            key=stored.key,
            kind=stored.kind,
            preview_url=stored.url,
        )
    )


@router.get("/files/{file_id}")
async def get_file(
    file_id: str,
    user_id: Annotated[str, Depends(current_user_id)],
    download: bool = False,
) -> Response:
    """回读已上传的文件（图片 / 文档）。

    两种后端都能用：

    * **oss** —— 307 跳转到签名 URL，流量不过后端进程
    * **local** —— 直接返回字节

    **Content-Type 按存储 key 的后缀给真实值**，不是一律
    ``application/octet-stream``：图片 ``<img>``、PDF 用浏览器内置查看器预览、
    前端 ESM 的 ``fetch().arrayBuffer()`` 都依赖它；``?download=1`` 时按附件下载。

    ``file_id`` 经 :func:`resolve_stored_key` 严格校验，非法或不存在一律 404。
    """
    try:
        backend = get_backend()
    except StorageError as exc:
        raise _storage_error(exc, user_id=user_id) from exc

    try:
        key, url = resolve_and_presign(file_id, backend=backend)
    except UploadRejectedError as exc:
        logger.warning("files.not_found", file_id=file_id, user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except StorageError as exc:
        raise _storage_error(exc, user_id=user_id, file_id=file_id) from exc

    # OSS 签名 URL 是绝对地址且已是公网可达；本地后端给出的是本端点相对路径
    if url.startswith(("http://", "https://")):
        return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    try:
        data = load_stored_bytes(file_id, backend=backend)
    except UploadRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except StorageError as exc:
        raise _storage_error(exc, user_id=user_id, file_id=file_id) from exc

    return Response(
        content=data,
        media_type=mime_for_suffix(key.rsplit(".", 1)[-1]),
        headers={
            "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{file_id}"',
            # 预览面板每开一次都会重新拉，别让中间层缓存住旧内容
            "Cache-Control": "private, max-age=300",
        },
    )
