"""LLM 客户端工厂（多 provider）。

返回 LangChain 的 ``BaseChatModel`` 实例，注入 :func:`core.agent.build_core_agent`。

详见 :mod:`docs/design/architecture` §6 LLM 层 与 :mod:`docs.notes.llm-providers`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from core.utils.logging import get_logger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from core.config import LLMConfig

logger = get_logger(__name__)

ProviderName = Literal[
    "openai",
    "MiniMax",
    "deepseek",
    "zhipu",
    "moonshot",
    "anthropic",
    "custom",
    "litellm",
]


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """LLM provider 预设配置。

    Attributes:
        display_name: 人类可读名（用于日志 / 文档）。
        base_url: OpenAI-compatible endpoint。``None`` 表示使用官方默认。
        default_model: 推荐的默认模型名。
        env_key_hint: 在 ``.env.example`` 里给出的提示（base_url 行）。
        api_key_format: API key 的预期前缀（仅用于提示 / 校验，不强制）。
        notes: 额外说明（如 Anthropic 需要不同 SDK）。
    """

    display_name: str
    base_url: str | None
    default_model: str
    env_key_hint: str = ""
    api_key_format: str = ""
    notes: str = ""


# ── 预设表 ─────────────────────────────────────────────
# 新增 provider 时：在这里加一行即可
PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "litellm": ProviderPreset(
        display_name="LiteLLM",
        base_url="http://127.0.0.1:4000/v1",
        default_model="agent-main",
        notes="通过网关统一访问模型。",
    ),
    "openai": ProviderPreset(
        display_name="OpenAI",
        base_url=None,  # 用 https://api.openai.com/v1
        default_model="gpt-4o-mini",
        api_key_format="sk-...",
    ),
    "MiniMax": ProviderPreset(
        display_name="MiniMax（MiniMax）",
        base_url="https://api.MiniMax.com/v1",
        default_model="MiniMax-M2",
        env_key_hint="MiniMax 兼容 OpenAI 协议，使用 /v1 endpoint",
        api_key_format="eyJ... (JWT)",
        notes="Token Plan 用户也可使用同一 endpoint；模型名按订阅档位选择（M2 / M3 / M4）。",
    ),
    "deepseek": ProviderPreset(
        display_name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        api_key_format="sk-...",
    ),
    "zhipu": ProviderPreset(
        display_name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-plus",
        api_key_format="<hex>",
    ),
    "moonshot": ProviderPreset(
        display_name="Moonshot Kimi",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        api_key_format="sk-...",
    ),
    "anthropic": ProviderPreset(
        display_name="Anthropic Claude",
        base_url=None,
        default_model="claude-3-5-sonnet-latest",
        notes="需安装 langchain-anthropic；非 OpenAI 兼容，使用不同 SDK。",
    ),
    "custom": ProviderPreset(
        display_name="Custom OpenAI-compatible",
        base_url=None,  # 必填
        default_model="custom-model",
        notes="任意 OpenAI-compatible 协议；必须显式设置 base_url。",
    ),
}


__all__ = [
    "PROVIDER_PRESETS",
    "ProviderName",
    "ProviderPreset",
    "build_llm_client",
    "supports_vision",
]

#: 模型名里出现这些片段就当它支持图片输入（小写比较）。
#: 只做粗判 —— 拿不准时用户可以显式设 ``LLM_VISION=1/0`` 覆盖。
_VISION_MODEL_HINTS: tuple[str, ...] = (
    "minimax-m3",  # MiniMax-M3 / M3.1 原生支持 image_url（见官方 OpenAI SDK 文档）
    "m3.1",
    "gpt-4",
    "gpt-5",
    "o3",
    "o4",
    "claude",
    "gemini",
    "glm-4v",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "internvl",
    "llava",
    "kimi-latest",
)


def supports_vision(config: LLMConfig) -> bool:
    """当前模型能否直接看图。

    决定上传图片走哪条路：

    * ``True``  → 图片作为 ``image_url`` content part 直接给模型（准确、快）
    * ``False`` → 退回「落盘 + 沙箱里用代码处理」（见 api.routes.chat）

    优先级：显式配置 ``LLM_VISION`` > provider 常识（anthropic）> 模型名关键字。
    """
    if config.vision is not None:
        return config.vision
    if (config.provider or "").lower() == "anthropic":
        return True
    model = (config.model or "").lower()
    return any(hint in model for hint in _VISION_MODEL_HINTS)


def resolve_preset(config: LLMConfig) -> ProviderPreset:
    """根据 ``config.provider`` 查预设；不在表里时回退到 ``custom``。

    Args:
        config: LLM 配置。

    Returns:
        命中的 :class:`ProviderPreset`。
    """
    preset = PROVIDER_PRESETS.get(config.provider)
    if preset is not None:
        return preset

    return ProviderPreset(
        display_name=config.provider,
        base_url=config.base_url,
        default_model=config.model,
        notes="未在 PROVIDER_PRESETS 中注册的 provider，按 custom 处理。",
    )


def build_llm_client(config: LLMConfig) -> BaseChatModel:
    """构造 LLM 客户端。

    步骤：
        1. 查 :data:`PROVIDER_PRESETS` 拿到 ``base_url`` / ``default_model``
        2. 优先用 config 里显式给的 base_url / model（覆盖预设）
        3. 校验 api_key
        4. 按 provider 类型分发：
           * ``anthropic`` → :class:`ChatAnthropic`
           * 其它 → :class:`ChatOpenAI`（OpenAI-compatible）

    Args:
        config: LLM 配置（provider / api_key / base_url / model / timeout）。

    Returns:
        LangChain ``BaseChatModel`` 实例，可直接传入 ``create_deep_agent(model=...)``。

    Raises:
        ConfigError: api_key 缺失 / 未注册的 provider / custom 缺 base_url。
    """
    if not config.api_key:
        from core.exceptions import ConfigError

        raise ConfigError("LLM api_key 缺失，请设置 LLM_API_KEY 环境变量或 .env 文件。")

    preset = resolve_preset(config)
    base_url = config.base_url or preset.base_url
    model = config.model or preset.default_model

    # custom 必须显式给 base_url
    if config.provider == "custom" and not base_url:
        from core.exceptions import ConfigError

        raise ConfigError("provider=custom 时必须设置 LLM_BASE_URL 指向你的 endpoint")

    logger.info(
        "llm.client.build",
        provider=config.provider,
        display_name=preset.display_name,
        model=model,
        base_url=base_url,
        timeout=config.timeout_seconds,
    )

    # ── Anthropic 分支（非 OpenAI 协议）───────────────
    if config.provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:  # pragma: no cover
            from core.exceptions import ConfigError

            raise ConfigError(
                "使用 Anthropic provider 需要安装 langchain-anthropic：uv add langchain-anthropic"
            ) from exc

        return ChatAnthropic(
            model=model,
            api_key=config.api_key,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    # ── 默认：OpenAI 兼容协议 ─────────────────────────
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=config.api_key,
        base_url=base_url,
        # 自定义 base_url 默认不请求流式用量，追踪平台因此只能看到耗时。
        stream_usage=True,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )
