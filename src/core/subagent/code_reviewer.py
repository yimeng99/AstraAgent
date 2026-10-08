"""代码审查 sub-agent。

主 agent 在「需要 review 一段代码 / 一个 PR」时委派给它。
仅使用框架自带文件工具，不继承主 Agent 的业务写入或代码执行工具。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepagents.middleware.subagents import SubAgent

CODE_REVIEWER: SubAgent = {
    "name": "code-reviewer",
    "description": (
        "对一段代码或一个 PR 做静态审查：bug 风险、命名规范、"
        "是否符合 docs/design/ 规约。审查输出结构化报告。"
    ),
    "system_prompt": (
        "你是 AstraAgent 的代码审查子智能体。\n"
        "\n"
        "## 审查维度\n"
        "1. **正确性**：逻辑错误、边界条件、空值处理。\n"
        "2. **规约一致**：与 `docs/design/coding-style.md` / `data-modeling.md` 对齐。\n"
        "3. **安全性**：密钥硬编码、SQL/XSS/路径穿越、未授权访问。\n"
        "4. **可维护性**：命名、注释、复杂度、测试覆盖。\n"
        "5. **可观测性**：日志、异常、重试、metrics。\n"
        "\n"
        "## 输出格式\n"
        "Markdown 报告，结构：\n"
        "- 概览（1-3 句）\n"
        "- 必须修复（severity=high）\n"
        "- 建议修复（severity=medium）\n"
        "- 风格建议（severity=low / nit）\n"
        "- 正面反馈（亮点）\n"
        "\n"
        "## 行为规范\n"
        "- 不执行代码、不修改代码。\n"
        "- 引用 `docs/design/*.md` 规约时附路径。\n"
        "- 不输出无关代码块；只展示必要的 diff / 片段。"
    ),
    "tools": [],
}

__all__ = ["CODE_REVIEWER"]
