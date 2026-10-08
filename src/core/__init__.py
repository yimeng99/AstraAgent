"""AstraAgent 核心包 —— 主智能体编排与配置。

子模块：

* :mod:`core.config`   —— LLMConfig / AppConfig / load_app_config
* :mod:`core.llm`      —— LLM 客户端工厂
* :mod:`core.prompts`  —— 系统提示词
* :mod:`core.agent`    —— 主智能体工厂（deepagents）
* :mod:`core.cli`      —— CLI 入口

详见 :mod:`docs/design/architecture` §2 分层架构。
"""

from __future__ import annotations

from core.agent import build_core_agent, close_agent_resources, core_lifespan
from core.config import AppConfig, LLMConfig, WorkspaceConfig, load_app_config
from core.llm import build_llm_client

__version__ = "0.1.0"

__all__ = [  # noqa: RUF022  (grouped by category, not alphabetical)
    # 配置
    "AppConfig",
    "LLMConfig",
    "WorkspaceConfig",
    "load_app_config",
    # LLM
    "build_llm_client",
    # Agent
    "build_core_agent",
    "close_agent_resources",
    "core_lifespan",
    # 版本
    "__version__",
]
