"""查询应用密钥允许调用的模型，不向前端暴露网关凭证。"""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_config
from api.responses import ApiResult, success
from core.config import AppConfig
from core.llm import resolve_preset
from core.utils.logging import get_logger

router = APIRouter()
logger = get_logger("api.models")


class AvailableModel(BaseModel):
    id: str
    name: str
    description: str = ""


class ModelProvider(BaseModel):
    id: str
    name: str
    description: str = ""
    children: list[AvailableModel]


class AutomaticModel(BaseModel):
    id: str = "auto"
    name: str = "自动"
    description: str = "模型选择由系统内部来进行规划"


class ModelList(BaseModel):
    default: AutomaticModel = Field(default_factory=AutomaticModel)
    providers: list[ModelProvider]


@router.get("/models", response_model=ApiResult[ModelList])
async def list_models(cfg: Annotated[AppConfig, Depends(get_config)]):
    """按实际供应商分组，仅展示当前应用密钥可见的模型。"""
    llm = cfg.llm
    preset = resolve_preset(llm)
    provider = ModelProvider(
        id=llm.provider,
        name=preset.display_name,
        description="通过网关统一访问模型" if llm.provider == "litellm" else "直接连接模型服务商",
        children=[],
    )
    if llm.provider != "litellm":
        model = llm.model or preset.default_model
        provider.children = [AvailableModel(id=model, name=model, description="当前配置的直连模型")]
        return success(ModelList(providers=[provider]))

    base_url = llm.base_url or preset.base_url
    if not base_url or not llm.api_key:
        raise HTTPException(503, "模型网关尚未配置")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {llm.api_key}"},
            )
            response.raise_for_status()
            visible = {item["id"] for item in response.json()["data"]}
            response = await client.get(
                f"{base_url.rstrip('/')}/model/info",
                headers={"Authorization": f"Bearer {llm.api_key}"},
            )
            response.raise_for_status()
        items = response.json()["data"]
        if not isinstance(items, list):
            raise ValueError("invalid model list")
        providers: dict[str, ModelProvider] = {}
        seen: set[tuple[str, str]] = set()
        for item in items:
            model_id = item["model_name"]
            if not isinstance(model_id, str) or not model_id.strip():
                raise ValueError("invalid model id")
            if model_id not in visible:
                continue
            info = item.get("model_info") or {}
            if not isinstance(info, dict):
                raise ValueError("invalid model info")
            # 兼容协议不能推断真实供应商；优先使用网关配置中的明确标注。
            name = info.get("provider") or info.get("litellm_provider") or "未标注供应商"
            if not isinstance(name, str):
                raise ValueError("invalid provider")
            provider_id = name.casefold()
            if (provider_id, model_id) in seen:
                continue
            seen.add((provider_id, model_id))
            if provider_id not in providers:
                providers[provider_id] = ModelProvider(id=provider_id, name=name, children=[])
            providers[provider_id].children.append(
                AvailableModel(
                    id=model_id,
                    name=info.get("display_name") or model_id,
                    description=info.get("description") or "",
                )
            )
        return success(ModelList(providers=list(providers.values())))
    except httpx.TimeoutException:
        raise HTTPException(504, "获取模型列表超时，请稍后重试") from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # 不记录上游响应正文，避免错误内容带出渠道信息或凭证。
        logger.warning("models.list.failed", error_type=type(exc).__name__)
        raise HTTPException(502, "暂时无法获取模型列表，请稍后重试") from None
