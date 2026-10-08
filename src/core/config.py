"""应用配置聚合层。

* :class:`LLMConfig`        —— LLM 客户端（OpenAI 兼容）
* :class:`WorkspaceConfig`  —— 智能体运行时工作目录

入口 :func:`load_app_config` 从环境变量加载并校验。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final, Literal

from dotenv import load_dotenv
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)

from core.exceptions import ConfigError
from core.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "PROJECT_ROOT",
    "AppConfig",
    "LLMConfig",
    "StorageConfig",
    "WorkspaceConfig",
    "load_app_config",
    "resolve_project_path",
]

#: 项目根目录（``pyproject.toml`` 所在，即 ``src/core/config.py`` 往上两级）。
#:
#: **所有配置里的相对路径都以它为基准**，而不是当前工作目录 —— 否则同一个服务
#: 从不同目录启动会得到两份存储（踩过：``python src/api/main.py`` 时上传落到
#: ``src/api/workspace/uploads``，和根目录下的那份并存）。
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


def resolve_project_path(value: str | Path) -> Path:
    """把配置里的路径锚定到项目根：相对路径 → ``PROJECT_ROOT/...``；绝对路径原样返回。"""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


class LLMConfig(BaseModel):
    """LLM 客户端配置（OpenAI 兼容协议）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(
        default="openai",
        description="LLM 提供商：openai / azure / 自定义 OpenAI-compatible。",
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="模型名称（如 gpt-4o / gpt-4o-mini / deepseek-chat）。",
    )
    api_key: str = Field(
        default="",
        repr=False,
        description="LLM API Key。",
    )
    base_url: str | None = Field(
        default=None,
        description="OpenAI-compatible endpoint，覆盖默认 base_url。",
    )
    timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description="LLM 请求超时（秒）。",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=10,
        description="LLM 请求重试次数。",
    )
    vision: bool | None = Field(
        default=None,
        description=(
            "模型是否支持图片输入。None = 按 provider / 模型名自动判断"
            "（见 core.llm.supports_vision）。它决定上传的图片是直接作为"
            "多模态内容给模型，还是落盘后交给沙箱里的代码处理。"
        ),
    )


class WorkspaceConfig(BaseModel):
    """智能体运行时工作目录配置。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: Path = Field(
        default_factory=lambda: resolve_project_path("./workspace"),
        description="工作目录根路径。相对路径按 PROJECT_ROOT 解析（不是 CWD）。",
    )
    session_isolation: str = Field(
        default="per_session",
        description="session 隔离粒度：per_session | shared。",
    )
    retention_days: int = Field(
        default=30,
        ge=0,
        le=365,
        description="session 数据保留天数。",
    )

    @field_validator("session_isolation")
    @classmethod
    def _check(cls, v: str) -> str:
        if v not in {"per_session", "shared"}:
            raise ValueError("session_isolation 必须是 per_session 或 shared")
        return v


class StorageConfig(BaseModel):
    """上传文件的存储后端配置。

    默认 ``local``（落 ``workspace/uploads``），配齐 ``OSS_*`` 环境变量后
    切到 ``oss``。凭证字段一律 ``repr=False``，避免打进日志。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    driver: str = Field(
        default="local",
        description="存储驱动：local | oss。",
    )
    local_root: Path | None = Field(
        default=None,
        description="local 驱动的落盘根目录。None 则用 workspace.root/uploads。",
    )

    # ── 阿里云 OSS ──
    access_key_id: str = Field(default="", repr=False, description="OSS AccessKey ID。")
    access_key_secret: str = Field(default="", repr=False, description="OSS AccessKey Secret。")
    bucket: str = Field(default="", description="OSS Bucket 名。")
    endpoint: str = Field(default="", description="OSS Endpoint，如 oss-cn-hangzhou.aliyuncs.com。")
    prefix: str = Field(default="uploads", description="Bucket 内的 key 前缀。")

    @field_validator("driver")
    @classmethod
    def _check_driver(cls, v: str) -> str:
        if v not in {"local", "oss"}:
            raise ValueError("driver 必须是 local 或 oss")
        return v

    @field_validator("endpoint")
    @classmethod
    def _normalize_endpoint(cls, v: str) -> str:
        """oss2 要的是裸域名，带 scheme 会签名失败。"""
        v = v.strip().rstrip("/")
        for scheme in ("https://", "http://"):
            if v.startswith(scheme):
                v = v[len(scheme) :]
        return v

    @property
    def oss_configured(self) -> bool:
        """凭证是否齐全。缺任何一项都退回 local，而不是半配置状态连上去报错。"""
        return all((self.access_key_id, self.access_key_secret, self.bucket, self.endpoint))


class InvestmentHTTPConfig(BaseModel):
    """招商查询使用固定配置地址，避免模型自行指定外部请求目标。"""

    company_url: HttpUrl | None = None
    history_url: HttpUrl | None = None
    method: Literal["GET", "POST"] = "POST"
    api_key: str = Field(default="", repr=False)
    timeout_seconds: float = Field(default=30, ge=1, le=120, allow_inf_nan=False)


def load_investment_http_config() -> InvestmentHTTPConfig:
    return InvestmentHTTPConfig(
        company_url=os.getenv("INVESTMENT_COMPANY_URL") or None,
        history_url=os.getenv("INVESTMENT_HISTORY_URL") or None,
        method=os.getenv("INVESTMENT_HTTP_METHOD", "POST").upper(),
        api_key=os.getenv("INVESTMENT_API_KEY", ""),
        timeout_seconds=os.getenv("INVESTMENT_TIMEOUT_SECONDS", "30"),
    )


class TracingConfig(BaseModel):
    """通过 OTLP 向 Langfuse 上报；凭证不进入日志和模型上下文。"""

    model_config = ConfigDict(hide_input_in_errors=True)

    enabled: bool = False
    endpoint: str = "http://localhost:3100/api/public/otel/v1/traces"
    capture_content: bool = False
    public_key: str = Field(default="", repr=False)
    secret_key: SecretStr = Field(default=SecretStr(""), repr=False)
    sample_rate: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_credentials(self):
        if self.enabled and (not self.public_key or not self.secret_key.get_secret_value()):
            raise ValueError("启用追踪需要 LANGFUSE_PUBLIC_KEY 和 LANGFUSE_SECRET_KEY")
        return self

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT 必须是无凭证的 HTTP(S) 地址")
        return value


class AppConfig(BaseModel):
    """应用顶层聚合配置。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    recursion_limit: int = Field(default=125, ge=25, le=1000)

    llm: LLMConfig = Field(default_factory=LLMConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)


def _optional_bool(raw: str | None) -> bool | None:
    """把环境变量读成三态布尔：未设置 = ``None``（交给自动判断）。"""
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def load_app_config(*, dotenv_path: Path | None = None) -> AppConfig:
    """加载应用配置。

    1. 加载 ``.env``（如存在）到环境变量
    2. 读取 LLM 相关环境变量（必填 ``LLM_API_KEY``）
    3. 校验失败抛出 :class:`ConfigError`

    Args:
        dotenv_path: 自定义 .env 路径。

    Returns:
        校验通过的 :class:`AppConfig` 实例。

    Raises:
        ConfigError: 缺少必填环境变量或字段值非法。
    """
    load_dotenv(dotenv_path=dotenv_path, override=False)

    volume_root = os.getenv("SANDBOX_VOLUME_ROOT", "").strip()
    volume_enabled = os.getenv("SANDBOX_VOLUME_ENABLED", "false").strip().lower()
    if volume_enabled not in {"true", "false"}:
        raise ConfigError("SANDBOX_VOLUME_ENABLED 必须为 true 或 false")
    if volume_enabled == "true":
        from core.sandbox.provisioning import build_volume_path

        build_volume_path(volume_root, "", "config-validation")
        if not os.getenv("POSTGRES_URL", "").strip():
            raise ConfigError("启用沙箱数据卷时必须配置 POSTGRES_URL")

    # LangChain 原生读取这些变量；在启动时发现误配置，避免每次调用重复报错。
    tracing = os.getenv("LANGSMITH_TRACING", "false").strip().lower()
    if tracing not in {"true", "false"}:
        raise ConfigError("LANGSMITH_TRACING 必须为 true 或 false")
    if tracing == "true":
        if not os.getenv("LANGSMITH_API_KEY", "").strip():
            raise ConfigError("启用 LangSmith 追踪需要配置 LANGSMITH_API_KEY")
        endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
        if not endpoint.startswith(("https://", "http://")) or endpoint.endswith("/"):
            raise ConfigError("LANGSMITH_ENDPOINT 必须是 HTTP(S) 地址且不能以 / 结尾")
        logger.info("tracing.langsmith.enabled", project=os.getenv("LANGSMITH_PROJECT", "default"))

    api_key = os.getenv("LLM_API_KEY", "")
    if not api_key:
        raise ConfigError("缺少 LLM_API_KEY 环境变量，请检查 .env")

    try:
        llm_cfg = LLMConfig(
            provider=os.getenv("LLM_PROVIDER", "MiniMax"),
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL") or None,
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
            vision=_optional_bool(os.getenv("LLM_VISION")),
        )

        # 存储：显式 STORAGE_DRIVER=oss 才走 OSS；否则即便配了凭证也先用本地，
        # 免得开发机误连生产 bucket。凭证不全会退回 local 并告警。
        storage_cfg = StorageConfig(
            driver=os.getenv("STORAGE_DRIVER", "local"),
            local_root=(
                resolve_project_path(os.environ["STORAGE_LOCAL_ROOT"])
                if os.getenv("STORAGE_LOCAL_ROOT")
                else None
            ),
            access_key_id=os.getenv("OSS_ACCESS_KEY_ID", ""),
            access_key_secret=os.getenv("OSS_ACCESS_KEY_SECRET", ""),
            bucket=os.getenv("OSS_BUCKET", ""),
            endpoint=os.getenv("OSS_ENDPOINT", ""),
            prefix=os.getenv("OSS_PREFIX", "uploads"),
        )
        if storage_cfg.driver == "oss" and not storage_cfg.oss_configured:
            # 不直接失败：退回本地开发，业务能跑起来；告警足以让部署方发现
            logger.warning(
                "storage.oss.incomplete_fallback_local",
                hint="检查 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_BUCKET / OSS_ENDPOINT",
            )
            storage_cfg = storage_cfg.model_copy(update={"driver": "local"})

        # 工作目录：相对路径锚定到项目根（见 PROJECT_ROOT），避免"从哪个目录
        # 启动就落到哪里"——上传目录尤其不能随 CWD 漂移。
        workspace_cfg = WorkspaceConfig(
            root=resolve_project_path(os.getenv("AGENT_WORKSPACE") or "./workspace"),
        )

        tracing_cfg = TracingConfig(
            enabled=os.getenv("AGENT_TRACING_ENABLED", "false"),
            endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "http://localhost:3100/api/public/otel/v1/traces",
            ),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            sample_rate=os.getenv("AGENT_TRACING_SAMPLE_RATE", "1.0"),
            capture_content=os.getenv("AGENT_TRACING_CAPTURE_CONTENT", "false"),
        )
        return AppConfig(
            recursion_limit=os.getenv("AGENT_RECURSION_LIMIT", "125"),
            llm=llm_cfg,
            storage=storage_cfg,
            workspace=workspace_cfg,
            tracing=tracing_cfg,
        )
    except Exception as exc:
        raise ConfigError(f"配置校验失败：{exc}") from exc
