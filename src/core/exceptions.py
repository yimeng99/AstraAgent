"""核心包异常体系。"""

from __future__ import annotations


class AstraAgentError(Exception):
    """项目根异常，所有自定义异常的基类。"""


class ConfigError(AstraAgentError):
    """配置缺失、类型错误或校验失败。"""


__all__ = ["AstraAgentError", "ConfigError"]
