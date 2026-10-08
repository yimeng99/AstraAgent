"""沙箱管理器全局注册表。

在 :func:`core.agent.core_lifespan` 的启动 / 关闭钩子里调用
:func:`init_sandbox` 与 :func:`shutdown_sandbox`。

未配置 ``SANDBOX_BASE_URL`` 时，:func:`init_sandbox` 记一条 warning 就返回，
不抛异常 —— 沙箱是**可选能力**，没装 OpenSandbox 的环境依然要能正常对话。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from core.sandbox.config import SandboxConfig, load_sandbox_config
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from core.sandbox.service import SandboxService

logger = get_logger(__name__)

__all__ = [
    "get_sandbox_manager",
    "init_sandbox",
    "sandbox_available",
    "shutdown_sandbox",
]

_lock = threading.Lock()
_manager: SandboxService | None = None
_config: SandboxConfig | None = None


def init_sandbox(config: SandboxConfig | None = None) -> SandboxService | None:
    """创建全局沙箱管理器。

    Args:
        config: 沙箱配置；不给则从环境变量读取。

    Returns:
        管理器实例；未配置或 SDK 缺失时返回 ``None``（调用方应降级）。
    """
    global _manager, _config

    with _lock:
        if _manager is not None:
            return _manager

        cfg = config or load_sandbox_config()
        _config = cfg

        if not cfg.enabled:
            logger.info("sandbox.disabled", reason="SANDBOX_BASE_URL 未配置")
            return None

        try:
            from core.sandbox.service import SandboxService

            _manager = SandboxService(cfg)
        except Exception:
            # 沙箱起不来不应拖垮整个应用 —— 记日志并降级
            logger.exception("sandbox.init.failed")
            _manager = None
            return None

        logger.info(
            "sandbox.init.ok",
            image=cfg.image,
            volume_enabled=cfg.volume_enabled,
        )
        return _manager


def get_sandbox_manager() -> SandboxService | None:
    """取全局管理器；未初始化返回 ``None``。"""
    return _manager


def sandbox_available() -> bool:
    """沙箱是否已就绪。**不主动发起健康探测**（避免每次调用都打网络）。"""
    return _manager is not None


def shutdown_sandbox() -> None:
    """关闭本地沙箱服务。应在应用关闭时调用。"""
    global _manager, _config

    with _lock:
        manager = _manager
        _manager = None
        _config = None

    if manager is None:
        return

    try:
        manager.shutdown()
        logger.info("sandbox.shutdown.ok")
    except Exception:
        logger.exception("sandbox.shutdown.failed")
