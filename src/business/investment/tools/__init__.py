"""招商工具注册入口。"""

from business.investment.tools.research import run_investment_research

TOOLS = (run_investment_research,)
for registered_tool in TOOLS:
    registered_tool.metadata = {"approval_mode": "read_only"}
