"""企业和历史招商信息查询；请求字段集中在此适配实际业务接口。"""

from langchain_core.tools import tool

from business.investment.tools.http import request_data
from core.config import load_investment_http_config


@tool
async def investment_company_profile(company_name: str) -> dict:
    """通过业务 HTTP 接口查询企业资料；失败或未配置不代表企业没有风险。"""
    if load_investment_http_config().company_url is None:
        return {
            "status": "mock",
            "source": "本地模拟数据，非真实企业信息",
            "data": {
                "company_name": company_name,
                "industry": "新能源储能设备（模拟）",
                "operating_status": "存续（模拟）",
                "registered_capital_wan": 10000,
            },
            "message": "仅用于流程演示，不可据此判断真实企业信用和经营风险",
        }
    return await request_data("company_url", {"company_name": company_name})


@tool
async def investment_historical_cases(industry: str, park_name: str | None = None) -> dict:
    """通过业务 HTTP 接口查询同产业、同园区的历史招商项目。"""
    if load_investment_http_config().history_url is None:
        return {
            "status": "mock",
            "source": "本地模拟数据，非真实历史招商案例",
            "data": [
                {
                    "project_name": "示例招商项目",
                    "industry": industry,
                    "park_name": park_name,
                    "total_investment_wan": 30000,
                    "land_area_mu": 60,
                    "annual_output_wan": 50000,
                    "annual_tax_wan": 2000,
                }
            ],
            "message": "仅用于演示，不能作为真实预测或准入阈值依据",
        }
    return await request_data("history_url", {"industry": industry, "park_name": park_name})
