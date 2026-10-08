"""主 Agent 的招商研判入口；查询和核算由图统一调度。"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool
from pydantic import Field

from business.investment.models import AdmissionRules, ProjectBrief


@tool
async def run_investment_research(
    company_name: Annotated[str, Field(min_length=1, max_length=200)],
    config: RunnableConfig,
    project: ProjectBrief | None = None,
    rules: AdmissionRules | None = None,
    focus: str = "判断是否值得重点跟进",
) -> dict:
    """按招商图执行企业调查、历史查询、产业与准入、政策、风险和评分检查。

    仅企业名称必填，收到名称即可启动；项目资料和准入规则均可后续补充。
    有材料时提取项目字段，金额万元、面积亩；未知字段保持为空。
    返回含原始证据、缺失项和模拟标识的结构化结果，供主 Agent 再加工。
    不能把模拟数据当作企业事实，不能凭空填入准入规则或评分。
    """
    # 延迟导入避免 tools 注册入口和工作流内部工具之间的循环依赖。
    from business.investment.workflow import investment_graph

    company_name = company_name.strip()
    if not company_name:
        raise ToolException("企业名称不能为空")
    if project is not None and project.company_name.strip() != company_name:
        raise ToolException("企业名称与项目资料不一致，请确认研判对象")
    project = project or ProjectBrief(company_name=company_name)

    state = await investment_graph.ainvoke(
        {
            "project": project.model_dump(mode="json"),
            "rules": rules.model_dump(mode="json") if rules else None,
            "focus": focus,
        },
        config=config,
    )
    return state["result"]
