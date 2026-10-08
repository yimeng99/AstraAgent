"""内置子 Agent 原生配置；在这里汇总，由 agent.py 统一加上审批保护。"""

from __future__ import annotations

from core.subagent.code_reviewer import CODE_REVIEWER
from core.subagent.ragwiki_agent import RAGWIKI_AGENT

BUILTIN_SUBAGENTS = (RAGWIKI_AGENT, CODE_REVIEWER)

__all__ = ["BUILTIN_SUBAGENTS"]
