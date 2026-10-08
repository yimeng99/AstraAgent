"""对象存储抽象：本地磁盘 / 阿里云 OSS。

为什么抽这一层：上传、预览、沙箱同步三处都要"存进去 / 取出来"，但落点
可以是本地磁盘也可以是 OSS。抽象成 :class:`StorageBackend` 后，三个调用点
都不需要知道底层是谁。

**安全约束（选 OSS 时尤其重要）**：

* ``key`` 一律由服务端生成（``{file_id}.{suffix}``），客户端文件名绝不参与，
  否则 ``../../etc/passwd`` 这类 key 会逃出 bucket 前缀。
* Bucket 建议保持**私有**，预览走后端签发的短期签名 URL。若图省事设成
  公共读，等于把所有人的上传图片公开可枚举。
* 签名 URL 有有效期，前端拿到就能用；不要把永久公网 URL 写进响应。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from core.config import StorageConfig

logger = get_logger(__name__)

__all__ = [
    "FILES_URL_PREFIX",
    "PRESIGN_TTL_SECONDS",
    "LocalBackend",
    "OssBackend",
    "StorageBackend",
    "StorageError",
    "StoredObject",
    "get_backend",
]


class StorageError(RuntimeError):
    """存储后端不可用或操作失败。

    与 :class:`api.storage.UploadRejectedError` 分开：前者是**基础设施**问题
    （OSS 超时、凭证错），后者是**用户输入**问题（类型不符、超大）。
    调用方应对前者返 5xx，后者返 4xx。
    """


@dataclass(frozen=True, slots=True)
class StoredObject:
    """一个已存入的对象。"""

    #: 后端内部标识（本地是相对路径，OSS 是 object key）
    key: str
    #: 可直接给浏览器用的 URL（本地走回读端点，OSS 走签名 URL）
    url: str
    size: int


class StorageBackend(Protocol):
    """存储后端协议。

    实现方只需保证 ``put_bytes`` / ``get_bytes`` / ``exists`` / ``presign`` 语义
    正确；调用方不关心底层是磁盘还是 OSS。
    """

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def presign(self, key: str, *, expires_seconds: int) -> str:
        """返回可直接访问的临时 URL。"""
        ...

    def iter_keys(self) -> Iterator[str]:
        """列出所有 key（用于「按 file_id 找回后缀」等场景）。"""
        ...


#: 文件回读端点的 URL 前缀（本地后端把字节从这里吐出去）。
#: 前端下载卡片、产物清单、后端路由都指向它 —— 只有这一处定义。
FILES_URL_PREFIX: Final[str] = "/api/v1/files"

#: 预览签名 URL 有效期（秒）。够前端 <img> 加载完即可，不长期暴露。
PRESIGN_TTL_SECONDS: Final[int] = 15 * 60


# ── 本地磁盘 ────────────────────────────────────
class LocalBackend:
    """落盘到 ``workspace/uploads``（开发默认，无外部依赖）。"""

    def __init__(self, root: Path, *, url_prefix: str = FILES_URL_PREFIX) -> None:
        # 相对路径一律锚定到项目根：不能让它跟着 CWD 走，否则从 src/api 启动服务
        # 会写出第二份 workspace/uploads（见 core.config.resolve_project_path）。
        from core.config import resolve_project_path

        self._root = resolve_project_path(root)
        self._url_prefix = url_prefix

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, key: str) -> Path:
        """把 key 拼成绝对路径，并确认没有逃出 root。

        key 来自客户端（经 file_id 反推），**必须**当不可信输入处理。
        """
        if not key or Path(key).name != key or key in {".", ".."}:
            raise StorageError("非法的对象 key")
        target = (self._root / key).resolve()
        if not target.is_relative_to(self._root.resolve()):
            raise StorageError("对象 key 越界")
        return target

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)  # 原子替换，避免半截文件被读到
        return StoredObject(key=key, url=f"{self._url_prefix}/{key}", size=len(data))

    def get_bytes(self, key: str) -> bytes:
        target = self._resolve(key)
        if not target.is_file():
            raise StorageError("对象不存在")
        return target.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).is_file()
        except StorageError:
            return False

    def presign(self, key: str, *, expires_seconds: int) -> str:
        """本地没有签名概念，直接给回读端点 URL。"""
        return f"{self._url_prefix}/{key}"

    def iter_keys(self) -> Iterator[str]:
        if not self._root.is_dir():
            return
        for p in self._root.iterdir():
            if p.is_file() and not p.name.endswith(".part"):
                yield p.name


# ── 阿里云 OSS ──────────────────────────────────
class OssBackend:
    """阿里云 OSS（oss2 SDK）。

    构造时即校验配置；缺凭证直接抛 :class:`StorageError`，避免把问题拖到
    第一次上传才暴露。
    """

    def __init__(self, cfg: StorageConfig) -> None:
        # oss2 没有类型标记（missing py.typed），strict 模式下按 Any 处理
        import oss2  # type: ignore[import-untyped]

        if not (cfg.access_key_id and cfg.access_key_secret and cfg.bucket and cfg.endpoint):
            raise StorageError(
                "OSS 配置不完整（缺 access_key_id / access_key_secret / bucket / endpoint）"
            )

        self._cfg = cfg
        self._bucket_name = cfg.bucket
        self._oss = oss2.Auth(cfg.access_key_id, cfg.access_key_secret)
        self._bucket = oss2.Bucket(self._oss, cfg.endpoint, cfg.bucket)
        self._prefix = cfg.prefix.strip("/")

        # 建连 + 读权限探针。凭证错 / endpoint 错 / bucket 不存在都在这里暴露。
        try:
            self._bucket.get_bucket_info()
        except Exception as exc:  # oss2 的异常层级较杂，统一收敛
            raise StorageError(f"OSS 连接失败：{exc}") from exc

    def _full_key(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise StorageError("非法的 object key")
        return f"{self._prefix}/{key}" if self._prefix else key

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        headers = {"Content-Type": content_type} if content_type else None
        try:
            self._bucket.put_object(self._full_key(key), data, headers=headers)
        except Exception as exc:
            raise StorageError(f"OSS 上传失败：{exc}") from exc
        return StoredObject(
            key=key,
            url=self.presign(key, expires_seconds=PRESIGN_TTL_SECONDS),
            size=len(data),
        )

    def get_bytes(self, key: str) -> bytes:
        try:
            result = self._bucket.get_object(self._full_key(key))
            return bytes(result.read())
        except Exception as exc:
            raise StorageError(f"OSS 读取失败：{exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            return bool(self._bucket.object_exists(self._full_key(key)))
        except Exception:
            return False

    def presign(self, key: str, *, expires_seconds: int = PRESIGN_TTL_SECONDS) -> str:
        try:
            return str(
                self._bucket.sign_url("GET", self._full_key(key), expires_seconds, slash_safe=True)
            )
        except Exception as exc:
            raise StorageError(f"OSS 签名失败：{exc}") from exc

    def iter_keys(self) -> Iterator[str]:
        import oss2

        prefix = f"{self._prefix}/" if self._prefix else ""
        try:
            for obj in oss2.ObjectIterator(self._bucket, prefix=prefix):
                name = obj.key[len(prefix) :] if prefix else obj.key
                if name:
                    yield name
        except Exception as exc:
            raise StorageError(f"OSS 列举失败：{exc}") from exc


# ── 全局单例 ────────────────────────────────────
_backend: StorageBackend | None = None


def get_backend(cfg: StorageConfig | None = None) -> StorageBackend:
    """取全局后端，首次调用时按配置构造。

    Args:
        cfg: 存储配置。``None`` 时从 :func:`core.config.load_app_config` 取。
            显式传入便于测试注入。

    Returns:
        已就绪的 :class:`StorageBackend`。
    """
    global _backend
    if _backend is not None:
        return _backend

    if cfg is None:
        from core.config import load_app_config

        cfg = load_app_config().storage

    if cfg.driver == "oss":
        _backend = OssBackend(cfg)
        logger.info("storage.backend", driver="oss", bucket=cfg.bucket, prefix=cfg.prefix)
    else:
        from core.config import load_app_config as _load

        root = cfg.local_root
        if root is None:
            root = _load().workspace.root / "uploads"
        _backend = LocalBackend(root)
        logger.info("storage.backend", driver="local", root=str(root))

    return _backend
