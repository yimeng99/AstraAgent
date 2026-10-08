"""对错误信息 / 工具输出脱敏。

生产环境对用户的回复里**不能**包含：

* 环境变量名（RAGWIKI_*、POSTGRES_*、LLM_*）
* URL 中的凭证（``user:pass@host``）
* 内部代码路径（``src/...``、``.venv/...``）
* 应用凭证（``cli_xxx``、``rwk_xxx``、``eyJ...`` JWT）

脱敏函数 :func:`redact` 用于所有 ``@tool`` 函数返回给 LLM 的字符串；
详细信息留在日志（structlog）里，**不进** LLM context，**不进** 用户回复。
"""

from __future__ import annotations

import re

__all__ = ["redact", "safe_error_message"]


# 敏感模式（按出现顺序匹配）
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 环境变量赋值 / 引用（KEY=val 或 $KEY）
    (re.compile(r"\b[A-Z][A-Z0-9_]+_(?:KEY|TOKEN|SECRET|URL|PASSWORD)\b"), "***"),
    # URL 含 user:pass@（如 postgresql://root:1234@host）
    (re.compile(r"://[^\s:@/]+:[^\s@/]+@"), "://***@"),
    # JWT (eyJ...) 与长随机凭证
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{16,}\b"), "***JWT***"),
    (re.compile(r"\b(?:cli_|rwk_|sk-)[A-Za-z0-9_\-]{12,}\b"), "***KEY***"),
    # 内部路径
    (re.compile(r"[A-Za-z]:[\\\\/](?:[^\\\\/\s]*[\\\\/])*src[\\\\/][^\s)\\]'\"]+"), "***PATH***"),
    (re.compile(r"/(?:[^/\s]+/)*src/[^\\s)\\]'\"]+"), "***PATH***"),
    # ~/.lark-cli / ~/.cache 等内部 cache 路径
    (re.compile(r"~[\\\\/]\.[A-Za-z][^\s)\\]'\"]+"), "***PATH***"),
)


def redact(text: str, *, replacement: str = "***") -> str:
    """把字符串里的敏感信息替换成 ``replacement``。

    Args:
        text: 原始字符串（错误信息 / 工具输出）。
        replacement: 替换字符串，默认 ``***``。

    Returns:
        脱敏后的字符串。
    """
    out = text
    for pat, rep in _PATTERNS:
        # 如果全局 replacement 是 ***，模式自带的替代字符优先级更高
        out = pat.sub(rep if rep != "***" else replacement, out)
    return out


def safe_error_message(
    exc: BaseException,
    *,
    fallback: str = "操作失败，请稍后重试",
) -> str:
    """构造对用户友好的错误信息。

    流程：
        1. 取 ``type(exc).__name__ + ':' + str(exc)``
        2. 过 :func:`redact`
        3. 截断（防止 stacktrace 超长）

    Args:
        exc: 异常对象。
        fallback: 当完全没法构造信息时使用的兜底文案。
    """
    raw = f"{type(exc).__name__}: {exc}"
    cleaned = redact(raw).strip()
    if not cleaned or cleaned == ":":
        return fallback
    # 截断到 200 字
    if len(cleaned) > 200:
        cleaned = cleaned[:200] + "…"
    return cleaned
