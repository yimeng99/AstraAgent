"""招商研判的数据契约；未知指标保持为空，不把缺失当作零。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    company_name: str = Field(min_length=1, max_length=200)
    project_name: str | None = Field(default=None, min_length=1, max_length=200)
    park_name: str | None = None
    industry: str | None = None
    total_investment_wan: float | None = Field(default=None, ge=0)
    fixed_asset_investment_wan: float | None = Field(default=None, ge=0)
    land_area_mu: float | None = Field(default=None, gt=0)
    annual_output_wan: float | None = Field(default=None, ge=0)
    annual_tax_wan: float | None = Field(default=None, ge=0)
    sources: list[str] = Field(default_factory=list)


class AdmissionRules(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    park_name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source: str = Field(min_length=1)
    investment_basis: Literal["total", "fixed_assets"]
    min_investment_wan_per_mu: float | None = Field(default=None, ge=0)
    min_output_wan_per_mu: float | None = Field(default=None, ge=0)
    min_tax_wan_per_mu: float | None = Field(default=None, ge=0)


class MetricResult(BaseModel):
    metric: str
    status: Literal["passed", "failed", "insufficient_data", "not_configured"]
    value: float | None = None
    threshold: float | None = None
    unit: str = "万元/亩"


class ReviewResult(BaseModel):
    project: ProjectBrief
    metrics: list[MetricResult]
    missing_fields: list[str]
    conclusion: Literal["pending_due_diligence", "admission_failed", "insufficient_data"]
    rules_version: str | None = None
    rules_source: str | None = None
    warnings: list[str] = Field(default_factory=list)
