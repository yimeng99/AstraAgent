"""主 Agent 直接调用招商图，不再注册招商子 Agent。"""

from business.investment.tools import TOOLS

SUBAGENTS = ()

__all__ = ["SUBAGENTS", "TOOLS"]
