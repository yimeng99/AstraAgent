"""招商指标核算集中在工具内，缺失的准入标准不能猜测。"""

from langchain_core.tools import ToolException, tool

from business.investment.models import AdmissionRules, MetricResult, ProjectBrief, ReviewResult


def review_project(project: ProjectBrief, rules: AdmissionRules | None = None) -> ReviewResult:
    if rules and project.park_name != rules.park_name:
        raise ToolException("项目园区与准入规则园区不一致，请先确认目标园区")
    investment = (
        project.total_investment_wan
        if rules and rules.investment_basis == "total"
        else project.fixed_asset_investment_wan
    )
    inputs = (
        ("investment_intensity", investment, rules.min_investment_wan_per_mu if rules else None),
        (
            "output_per_mu",
            project.annual_output_wan,
            rules.min_output_wan_per_mu if rules else None,
        ),
        ("tax_per_mu", project.annual_tax_wan, rules.min_tax_wan_per_mu if rules else None),
    )
    metrics = []
    for name, amount, threshold in inputs:
        value = (
            amount / project.land_area_mu if amount is not None and project.land_area_mu else None
        )
        status = (
            "not_configured"
            if threshold is None
            else "insufficient_data"
            if value is None
            else "passed"
            if value >= threshold
            else "failed"
        )
        metrics.append(MetricResult(metric=name, value=value, threshold=threshold, status=status))
    required = ["park_name", "industry", "land_area_mu", "annual_output_wan", "annual_tax_wan"]
    required.append(
        "total_investment_wan"
        if rules and rules.investment_basis == "total"
        else "fixed_asset_investment_wan"
    )
    missing = [name for name in required if getattr(project, name) is None]
    failed = any(item.status == "failed" for item in metrics)
    complete = all(item.status == "passed" for item in metrics)
    return ReviewResult(
        project=project,
        metrics=metrics,
        missing_fields=missing,
        conclusion="admission_failed"
        if failed
        else "pending_due_diligence"
        if complete and not missing
        else "insufficient_data",
        rules_version=rules.version if rules else None,
        rules_source=rules.source if rules else None,
        warnings=[
            "数值核算不代表完整准入、产业匹配或政策资格审核。",
            "预测指标和规则来源仍需核实；未配置综合评分规则，不输出评分。",
        ],
    )


@tool
def investment_review_project(project: ProjectBrief, rules: AdmissionRules | None = None) -> dict:
    """核算投资强度、亩均产值和税收，金额万元、面积亩，规则必须有明确来源。"""
    return review_project(project, rules).model_dump(mode="json")
