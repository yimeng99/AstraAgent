"""上传文件的校验与存储编排。

安全约束（这里就是攻击面，必须收紧）：

* **文件名不可信** —— 一律丢弃，只用服务端生成的 ``{file_id}{suffix}``，
  否则 ``../../etc/passwd`` 或 Windows 保留名会逃出上传目录。
* **大小先限后读** —— 先看 ``Content-Length`` 粗筛，再按 chunk 读并累加，
  超限立刻中断；不能 ``await file.read()`` 把整个文件塞进内存。
* **类型按魔数判定** —— ``content_type`` 由客户端提供、可伪造，
  真实类型见 :mod:`core.documents`（改扩展名绕不过）。
* **落点由后端决定** —— 本地磁盘或 OSS，见 :mod:`core.storage`。

本模块只管「校验 + 落库 + 回执」，怎么存由 :class:`~core.storage.StorageBackend` 决定。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from core.documents import (
    KIND_IMAGE,
    MAX_DOC_BYTES,
    DocumentError,
    detect_format,
)
from core.storage import FILES_URL_PREFIX, PRESIGN_TTL_SECONDS
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from fastapi import UploadFile

    from core.storage import StorageBackend

logger = get_logger(__name__)

__all__ = [
    "MAX_DOC_BYTES",
    "MAX_IMAGE_BYTES",
    "StoredFile",
    "UploadRejectedError",
    "load_stored_bytes",
    "resolve_and_presign",
    "resolve_stored_key",
    "sanitize_filename",
    "store_upload",
]

#: 单张图片大小上限（10 MiB）
MAX_IMAGE_BYTES: Final[int] = 10 * 1024 * 1024

#: 保留文件名（Windows 禁用，跨平台一律拒绝）
_RESERVED: Final[frozenset[str]] = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)

#: 展示名清洗：保留 ASCII 字母数字、中文、点、下划线、连字符与空格。
#: 中文文件名很常见（``测试图.png``），全替换成 ``_`` 会让用户认不出自己的文件。
_SAFE_NAME: Final[re.Pattern[str]] = re.compile(r"[^\w.\- ]", flags=re.UNICODE)

#: file_id 格式：32 位小写十六进制
_FILE_ID_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{32}")


class UploadRejectedError(ValueError):
    """上传被拒绝（类型不符 / 超大 / 魔数不匹配）。

    携带可直接展示给用户的中文文案；调用方转成 4xx。
    """


@dataclass(frozen=True, slots=True)
class StoredFile:
    """已存入存储后端的附件。"""

    file_id: str
    filename: str
    content_type: str
    size: int
    #: 后端内部 key（本地是相对文件名，OSS 是 object key）
    key: str
    #: 可直接给浏览器用的 URL
    url: str
    kind: str = "image"


def sanitize_filename(raw: str) -> str:
    """把客户端传来的文件名压成安全的展示名。

    只用于回显和日志，**不用于拼路径**（见 :func:`store_upload`）。
    """
    name = Path(raw or "").name  # 砍掉目录部分
    name = _SAFE_NAME.sub("_", name).strip("._") or "upload"
    if name.split(".")[0].lower() in _RESERVED:
        name = f"_{name}"
    return name[:120]


async def store_upload(
    file: UploadFile,
    *,
    filename: str,
    content_type: str,
    backend: StorageBackend | None = None,
    max_bytes: int | None = None,
) -> StoredFile:
    """校验并存入一个上传文件：**按魔数判定真实格式** → 边读边限流 → 交给后端。

    客户端自报的 ``content_type`` 只用于日志：真实类型一律由文件头 + 扩展名判定
    （见 :func:`core.documents.detect_format`），改扩展名绕不过去。

    Raises:
        UploadRejectedError: 类型不符或超限（用户输入问题 → 4xx）。
        core.storage.StorageError: 后端不可用（基础设施问题 → 5xx）。
    """
    safe_name = sanitize_filename(filename)

    # 先读一段验魔数 + 取扩展名
    head = await file.read(512)
    await file.seek(0)
    try:
        fmt = detect_format(head, safe_name)
    except DocumentError as exc:
        logger.warning("upload.rejected.format", filename=safe_name, error=str(exc))
        raise UploadRejectedError(str(exc)) from exc

    is_image = fmt.kind == KIND_IMAGE
    limit = max_bytes or (MAX_IMAGE_BYTES if is_image else MAX_DOC_BYTES)
    label = "图片" if is_image else "文件"

    file_id = uuid.uuid4().hex

    # 边读边限流并累加到内存。上限 10/20 MiB，整块驻留内存是可接受的 ——
    # 既能先完整校验再落库，也避免边写边超限留下半截对象。
    buf = bytearray()
    digest = hashlib.sha256()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        if len(buf) + len(chunk) > limit:
            raise UploadRejectedError(f"{label}过大，上限 {limit // (1024 * 1024)} MB")
        buf.extend(chunk)
        digest.update(chunk)

    data = bytes(buf)
    # key 只由服务端生成的 file_id + 判定出的后缀构成，客户端文件名绝不参与
    key = f"{file_id}.{fmt.suffix}"

    be = backend or _default_backend()
    stored = be.put_bytes(key, data, content_type=fmt.mime)

    # 本地后端的回读端点是 ``/api/v1/files/{file_id}``（**不带后缀**）——
    # 带后缀会被 resolve_stored_key 的 32 位 ID 校验拒掉，整条 URL 变 404
    # （气泡里的图片、附件的下载链接都靠它）。OSS 给的是签名 URL，原样保留。
    url = stored.url
    if url.startswith(f"{FILES_URL_PREFIX}/") and not url.startswith(("http://", "https://")):
        url = f"{FILES_URL_PREFIX}/{file_id}"

    logger.info(
        "upload.stored",
        file_id=file_id,
        key=key,
        size=len(data),
        kind="image" if is_image else "document",
        detected=fmt.mime,
        client_type=content_type,
        sha256=digest.hexdigest()[:16],
    )

    return StoredFile(
        file_id=file_id,
        filename=safe_name,
        content_type=fmt.mime,
        size=len(data),
        key=key,
        url=url,
        kind="image" if is_image else "document",
    )


def _default_backend() -> StorageBackend:
    """取全局存储后端。构造失败（OSS 配错）时原样抛出，交给上层转 5xx。"""
    from core.storage import get_backend

    return get_backend()


def resolve_stored_key(file_id: str, *, backend: StorageBackend | None = None) -> str:
    """按 ``file_id`` 找回对象 key。

    ``file_id`` 来自客户端，**必须**当作不可信输入处理：只接受 32 位小写
    十六进制。后缀不固定（取决于上传时的魔数判定），所以要在后端里查。

    Args:
        file_id: 上传时返回的 ID。
        backend: 存储后端。``None`` 时取全局单例。

    Returns:
        完整对象 key（如 ``{file_id}.png``）。

    Raises:
        UploadRejectedError: ID 格式非法，或对象不存在。
    """
    if not _FILE_ID_RE.fullmatch(file_id or ""):
        raise UploadRejectedError("附件 ID 格式非法")

    be = backend or _default_backend()
    for key in be.iter_keys():
        # key 形如 "{32位hex}.{后缀}"；前缀匹配已足够，且 file_id 已校验过
        if key.startswith(f"{file_id}."):
            return key

    raise UploadRejectedError("附件不存在或已过期")


def load_stored_bytes(
    file_id: str,
    *,
    backend: StorageBackend | None = None,
) -> bytes:
    """按 ``file_id`` 读出对象内容。

    Args:
        file_id: 上传时返回的 ID。
        backend: 存储后端。``None`` 时取全局单例。

    Returns:
        对象的完整字节内容。

    Raises:
        UploadRejectedError: ID 格式非法，或对象不存在。
    """
    from core.storage import StorageError

    key = resolve_stored_key(file_id, backend=backend)
    be = backend or _default_backend()
    try:
        return be.get_bytes(key)
    except StorageError:
        # 对象在列举与读取之间被删（并发），对调用方等价于"附件不存在"
        raise UploadRejectedError("附件不存在或已过期") from None


def resolve_and_presign(
    file_id: str,
    *,
    backend: StorageBackend | None = None,
    expires_seconds: int = PRESIGN_TTL_SECONDS,
) -> tuple[str, str]:
    """查一次，同时给回 ``(对象 key, 可直接用的 URL)``。

    key 的后缀要用来定 ``Content-Type``（OSS 靠它签名，本地靠它给响应头），
    分两次查会白跑一遍 ``iter_keys``。

    Raises:
        UploadRejectedError: ID 格式非法，或对象不存在。
    """
    key = resolve_stored_key(file_id, backend=backend)
    be = backend or _default_backend()
    return key, be.presign(key, expires_seconds=expires_seconds)
