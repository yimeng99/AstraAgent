"""招商研判图：业务步骤固定，结果和证据交回主 Agent 加工。"""

from typing import TypedDict

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException
from langgraph.graph import END, START, StateGraph

from business.investment.models import AdmissionRules, ProjectBrief
from business.investment.tools.queries import (
    investment_company_profile,
    investment_historical_cases,
)
from business.investment.tools.review import review_project


class ResearchState(TypedDict, total=False):
    """各节点共享的研判数据；total=False 允许字段随流程推进逐步补齐。"""

    project: dict  # 项目资料：企业、园区、产业、投资、用地、产值、税收及材料来源。
    rules: dict | None  # 园区准入规则：阈值、投资口径、来源和版本；为空时不能猜测标准。
    focus: str  # 用户本次研判的关注点，供主 Agent 加工最终答复。
    company: dict  # 企业查询结果，保留原始数据和模拟、成功或失败状态，便于核查依据。
    historical_cases: dict  # 同产业、同园区历史招商案例，保留来源与状态，供后续对比。
    industry_match: dict  # 园区产业匹配结果；没有产业目录时明确标记尚未接入。
    admission: dict  # 投资强度、亩均产值和税收的计算值、准入阈值、达标状态及缺失项。
    policies: dict  # 政策检索结果及检索状态；空结果不能直接解释为没有适用政策。
    risks: list[dict]  # 汇总证据缺口、指标未达标和待补充资料，供主 Agent 进一步分析。
    scoring: dict  # 综合评分及评分状态；没有明确评分规则时分数保持为空。
    result: dict  # 交回主 Agent 的结构化结果，保留证据和限制，供其组织答复或报告。


async def progress(config: RunnableConfig, stage: str, message: str) -> None:
    await adispatch_custom_event(
        "investment.progress", {"stage": stage, "message": message}, config=config
    )


async def parse_project(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "parse", "正在核对项目资料…")
    project = ProjectBrief.model_validate(state["project"])
    rules = AdmissionRules.model_validate(state["rules"]) if state.get("rules") else None
    if rules and project.park_name != rules.park_name:
        raise ToolException("项目园区与准入规则园区不一致，请先确认目标园区")
    return {
        "project": project.model_dump(mode="json"),
        "rules": rules.model_dump(mode="json") if rules else None,
    }


async def company(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "company", "正在查询企业资料…")
    return {
        "company": await investment_company_profile.ainvoke(
            {"company_name": state["project"]["company_name"]}, config=config
        )
    }


async def history(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "history", "正在查询历史招商项目…")
    project = state["project"]
    if not project.get("industry"):
        return {
            "historical_cases": {
                "status": "insufficient_data",
                "data": None,
                "message": "缺少产业信息，未执行案例查询",
            }
        }
    return {
        "historical_cases": await investment_historical_cases.ainvoke(
            {"industry": project["industry"], "park_name": project.get("park_name")}, config=config
        )
    }


async def industry(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "industry", "正在检查产业匹配依据…")
    return {
        "industry_match": {
            "status": "not_configured",
            "matched": None,
            "message": "尚未接入园区产业目录，不能判断产业匹配",
        }
    }


async def admission(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "admission", "正在核算投资强度、产值和税收…")
    project = ProjectBrief.model_validate(state["project"])
    rules = AdmissionRules.model_validate(state["rules"]) if state["rules"] else None
    return {"admission": review_project(project, rules).model_dump(mode="json")}


async def policy(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "policy", "正在检查政策检索能力…")
    return {
        "policies": {
            "status": "not_configured",
            "data": [],
            "message": "专属政策检索尚未接入，政策匹配需补充核实",
        }
    }


async def risk(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "risk", "正在汇总风险和待核实事项…")
    risks = []
    for section in ("company", "historical_cases", "industry_match", "policies"):
        status = state[section]["status"]
        if status != "ok":
            risks.append(
                {
                    "type": "evidence_gap",
                    "section": section,
                    "status": status,
                    "message": "模拟数据不能作为真实证据"
                    if status == "mock"
                    else state[section].get("message", "资料待核实"),
                }
            )
    for metric in state["admission"]["metrics"]:
        if metric["status"] == "failed":
            risks.append(
                {
                    "type": "metric_failed",
                    "metric": metric["metric"],
                    "value": metric["value"],
                    "threshold": metric["threshold"],
                }
            )
    if state["admission"]["missing_fields"]:
        risks.append(
            {"type": "missing_information", "fields": state["admission"]["missing_fields"]}
        )
    return {"risks": risks}


async def score(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "score", "正在检查评分依据…")
    return {
        "scoring": {
            "status": "not_configured",
            "score": None,
            "message": "未配置评分规则，不能生成综合分",
        }
    }


async def assemble(state: ResearchState, config: RunnableConfig) -> dict:
    await progress(config, "result", "研判资料已整理，正在生成答复…")
    return {
        "result": {
            "status": "partial",
            "project": state["project"],
            "focus": state.get("focus", ""),
            "company_findings": state["company"],
            "historical_cases": state["historical_cases"],
            "industry_match": state["industry_match"],
            "admission": state["admission"],
            "matched_policies": state["policies"],
            "risks": state["risks"],
            "scoring": state["scoring"],
            "recommendation": "信息不足，需补充尽调",
            "missing_information": state["admission"]["missing_fields"],
            "evidence": {
                "project_sources": state["project"]["sources"],
                "rules_source": state["admission"]["rules_source"],
                "rules_version": state["admission"]["rules_version"],
            },
            "warnings": [
                "模拟查询仅用于演示；产业目录、政策检索和评分规则尚未接入。",
                *state["admission"]["warnings"],
            ],
            "next_action": "主 Agent 按缺失项使用 ask_user 补充，重新调用本图；保留证据和计算结果加工答复。",
        }
    }


def build_investment_graph():
    graph = StateGraph(ResearchState)
    nodes = (
        ("parse", parse_project),
        ("company", company),
        ("history", history),
        ("industry", industry),
        ("admission", admission),
        ("policy", policy),
        ("risk", risk),
        ("score", score),
        ("result", assemble),
    )
    previous = START
    for name, node in nodes:
        graph.add_node(name, node)
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    # 本图无内部人工中断；补充信息走主 Agent 已有的持久化 ask_user 流程。
    # 不给业务图创建独立会话，避免把不同用户的调研状态缓存到共享键下。
    return graph.compile(name="investment-research")


investment_graph = build_investment_graph()


if __name__ == "__main__":
    print(investment_graph.invoke("帮我对高兴科技能源企业进行项目研判。"))
