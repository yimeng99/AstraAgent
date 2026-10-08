"""用户沙箱入口：数据库加锁 → 获取/创建 → 使用 → 释放；不缓存用户沙箱。"""

import logging
from contextlib import contextmanager
from datetime import UTC, datetime

from opensandbox.exceptions.sandbox import SandboxApiException, SandboxException
from opensandbox.sync.manager import SandboxManagerSync

from core.context_type import MemoryContext
from core.sandbox.config import SandboxConfig
from core.sandbox.provisioning import (
    build_volume_path,
    finish_user_operation,
    get_or_create_sandbox,
    sandbox_owner,
)
from core.sandbox.repository import get_user_sandbox, lock_user

logger = logging.getLogger(__name__)


class SandboxBusyError(RuntimeError):
    """同一用户已有操作占用沙箱。"""


class SandboxService:
    def __init__(self, config: SandboxConfig):
        self.config = config
        self._shutdown = False

    @contextmanager
    def acquire(self, context: MemoryContext, *, wait: bool = False):
        cfg = self.config
        if not isinstance(context, MemoryContext) or not context.user_id.strip():
            raise PermissionError("必须提供有效用户上下文")
        if self._shutdown:
            raise RuntimeError("沙箱服务已停止")
        if not cfg.database_url:
            raise RuntimeError("用户沙箱需要配置 POSTGRES_URL")
        if cfg.volume_enabled and not cfg.volume_root:
            raise RuntimeError("启用数据卷时需要配置 SANDBOX_VOLUME_ROOT")
        try:
            db = lock_user(cfg.database_url, context.user_id, 120 if wait else 0)
        except TimeoutError as exc:
            raise SandboxBusyError("用户沙箱正在使用中，请稍后重试") from exc
        sandbox = None
        try:
            sandbox, token = get_or_create_sandbox(db, context, cfg)
            try:
                yield sandbox
            except BaseException as exc:
                # 超时、SDK/网络错误或取消后，远程操作可能还在运行；保留占用标记。
                # PermissionError 也是 OSError，但本地路径/权限拒绝没有未完成的远程命令。
                uncertain = (
                    isinstance(exc, (SandboxException, TimeoutError, OSError))
                    and not isinstance(exc, PermissionError)
                ) or not isinstance(exc, Exception)
                if not uncertain:
                    finish_user_operation(db, cfg, sandbox.id, token)
                raise
            else:
                finish_user_operation(db, cfg, sandbox.id, token)
        finally:
            try:
                if sandbox is not None:
                    sandbox.close()
            finally:
                db.close()

    def shutdown(self):
        # API 实例退出只停止接收新操作，不销毁其他实例可能使用的远程沙箱。
        self._shutdown = True

    def get_status(self, context: MemoryContext) -> dict:
        import psycopg
        from psycopg.rows import dict_row

        result = dict(
            state="NOT_CREATED",
            available=False,
            busy=False,
            created_at=None,
            running_since=None,
            running_seconds=None,
        )
        cfg = self.config
        if not cfg or not cfg.database_url or (cfg.volume_enabled and not cfg.volume_root):
            return {**result, "state": "UNAVAILABLE"}
        control = None
        try:
            with psycopg.connect(cfg.database_url, row_factory=dict_row, connect_timeout=10) as db:
                record = get_user_sandbox(db, context.user_id)
            if not record:
                return result
            expected_path = (
                build_volume_path(cfg.volume_root, context.tenant_id, context.user_id)
                if cfg.volume_enabled
                else None
            )
            if record["volume_path"] != expected_path:
                raise PermissionError("用户沙箱归属不一致")
            control = SandboxManagerSync.create(connection_config=self.config.connection_config())
            info = control.get_sandbox_info(record["sandbox_id"])
            if (info.metadata or {}).get("astra_volume_owner") != sandbox_owner(
                expected_path, context
            ):
                raise PermissionError("远程沙箱归属标识不一致")
            state = info.status.state.upper()
            result.update(state=state, created_at=info.created_at)
            result["busy"] = bool((info.metadata or {}).get("astra_active_operation"))
            try:
                lock = lock_user(cfg.database_url, context.user_id, 0)
            except TimeoutError:
                result["busy"] = True
            else:
                lock.close()
            result["available"] = state == "RUNNING" and not result["busy"]
            if state == "RUNNING" and info.status.last_transition_at is not None:
                since = info.status.last_transition_at
                if since.tzinfo is None:
                    since = since.replace(tzinfo=UTC)
                result.update(
                    running_since=since,
                    running_seconds=max(0, int((datetime.now(UTC) - since).total_seconds())),
                )
            elif state == "PAUSED":
                result["running_seconds"] = 0
        except Exception as exc:
            result["state"] = (
                "MISSING"
                if isinstance(exc, SandboxApiException) and exc.status_code == 404
                else "UNAVAILABLE"
            )
            logger.warning("用户沙箱查询失败：%s", type(exc).__name__)
        finally:
            if control is not None:
                control.close()
        return result
