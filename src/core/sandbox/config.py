"""沙箱配置 —— 从 ``SANDBOX_*`` 环境变量加载。

设计原则：**全部可选**。没配 ``SANDBOX_BASE_URL`` 就视为「未启用沙箱」，
上层据此降级，而不是启动时报错 —— 这样没装 OpenSandbox 的开发机
依然能跑通整个 agent。
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["SandboxConfig", "load_sandbox_config"]


class SandboxConfig(BaseModel):
    """沙箱连接与生命周期参数。

    Attributes:
        base_url: OpenSandbox 控制面地址。**空串 = 未启用**。
        api_key: 访问凭证（可选，部分部署不需要）。
        image: 沙箱镜像。
        max_sandboxes / idle_ttl_seconds / cleanup_interval_seconds:
            旧配置兼容字段，当前 PostgreSQL 流程不使用；不是集群容量或回收保证。
        cpu / memory: 单沙箱资源上限。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = ""
    api_key: str = ""
    use_server_proxy: bool = False
    image: str = "python:3.11-slim"
    max_sandboxes: int = Field(default=4, ge=1, le=64)
    idle_ttl_seconds: int = Field(default=600, ge=60, le=86400)
    cleanup_interval_seconds: int = Field(default=30, ge=5, le=3600)
    cpu: str = "1"
    memory: str = "1Gi"
    volume_enabled: bool = False
    volume_root: str = ""
    database_url: str = Field(default="", repr=False)

    @property
    def enabled(self) -> bool:
        """是否配置齐全。未配置时上层应降级而非报错。"""
        return bool(self.base_url.strip())

    def resource(self) -> dict[str, str]:
        """转成 OpenSandbox 的 resource 参数。"""
        return {"cpu": self.cpu, "memory": self.memory}

    def connection_config(self) -> Any:
        """构造 OpenSandbox 的 ``ConnectionConfigSync``。

        该类的入参是 ``domain`` + ``protocol``（**没有** ``base_url``），
        本方法负责把 ``SANDBOX_BASE_URL`` 拆成这两部分。

        Raises:
            RuntimeError: 未配置 ``base_url`` 或 ``opensandbox`` 未安装。
        """
        if not self.enabled:
            raise RuntimeError("沙箱未配置（缺少 SANDBOX_BASE_URL）")
        try:
            from opensandbox.config.connection_sync import ConnectionConfigSync
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("未安装 opensandbox，请执行：uv add deepagents-opensandbox") from exc

        domain, protocol = self._split_base_url(self.base_url)
        return ConnectionConfigSync(
            domain=domain,
            protocol=protocol,
            api_key=self.api_key or None,
            use_server_proxy=self.use_server_proxy,
        )

    @staticmethod
    def _split_base_url(raw: str) -> tuple[str, str]:
        """把 base URL 拆成 ``(domain, protocol)``。

        ``https://sandbox.example.com:8080`` → ``("sandbox.example.com:8080", "https")``。
        缺协议时按 http 处理。
        """
        url = raw.strip().rstrip("/")
        if "://" in url:
            protocol, _, domain = url.partition("://")
        else:
            protocol, domain = "http", url
        if not domain:
            raise RuntimeError(f"SANDBOX_BASE_URL 不合法：{raw!r}")
        return domain, protocol

    @property
    def idle_ttl(self) -> timedelta:
        return timedelta(seconds=self.idle_ttl_seconds)

    @property
    def cleanup_interval(self) -> timedelta:
        return timedelta(seconds=self.cleanup_interval_seconds)


def load_sandbox_config() -> SandboxConfig:
    """从环境变量读取配置；挂载开关只接受 true/false，避免拼写错误改变存储方式。"""

    def _int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, "") or default)
        except ValueError:
            return default

    volume_enabled = os.getenv("SANDBOX_VOLUME_ENABLED", "false").strip().lower()
    if volume_enabled not in {"true", "false"}:
        raise ValueError("SANDBOX_VOLUME_ENABLED 必须为 true 或 false")
    use_server_proxy = os.getenv("SANDBOX_USE_SERVER_PROXY", "false").strip().lower()
    if use_server_proxy not in {"true", "false"}:
        raise ValueError("SANDBOX_USE_SERVER_PROXY 必须为 true 或 false")

    return SandboxConfig(
        base_url=os.getenv("SANDBOX_BASE_URL", ""),
        api_key=os.getenv("SANDBOX_API_KEY", ""),
        use_server_proxy=use_server_proxy == "true",
        image=os.getenv("SANDBOX_IMAGE", "python:3.11-slim"),
        # 注意别写成 SANDBOX_MAX_SANDBBOXES（多一个 B）：环境变量名拼错不会报错，
        # 只会静默回落到默认值 4，用户配的并发上限就不生效了。
        max_sandboxes=_int("SANDBOX_MAX_SANDBOXES", 4),
        idle_ttl_seconds=_int("SANDBOX_IDLE_TTL_SECONDS", 600),
        cleanup_interval_seconds=_int("SANDBOX_CLEANUP_INTERVAL_SECONDS", 30),
        cpu=os.getenv("SANDBOX_CPU", "1"),
        memory=os.getenv("SANDBOX_MEMORY", "1Gi"),
        volume_enabled=volume_enabled == "true",
        volume_root=os.getenv("SANDBOX_VOLUME_ROOT", ""),
        database_url=os.getenv("POSTGRES_URL", ""),
    )
