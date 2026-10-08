"""招商查询的 HTTP 公共入口，不接受模型提供的任意 URL。"""

import httpx
from pydantic import ValidationError

from core.config import load_investment_http_config
from core.utils.logging import get_logger

logger = get_logger(__name__)


async def request_data(endpoint: str, payload: dict) -> dict:
    try:
        config = load_investment_http_config()
    except ValidationError:
        logger.warning("investment.http.invalid_config")
        return {"status": "error", "message": "招商 HTTP 配置无效，请检查地址、方法和超时"}
    url = getattr(config, endpoint)
    if url is None:
        return {"status": "not_configured", "data": None, "message": "尚未配置该招商数据接口"}
    headers = {"X-API-Key": config.api_key} if config.api_key else {}
    payload = {key: value for key, value in payload.items() if value is not None}
    try:
        # 不自动跟随重定向，避免把认证头发送到配置地址之外。
        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            response = await client.request(
                config.method,
                str(url),
                headers=headers,
                **({"params": payload} if config.method == "GET" else {"json": payload}),
            )
            response.raise_for_status()
            return {"status": "ok", "data": response.json()}
    except httpx.TimeoutException:
        message = "招商数据接口请求超时"
    except httpx.HTTPStatusError as exc:
        message = f"招商数据接口返回 HTTP {exc.response.status_code}"
    except httpx.RequestError:
        message = "无法连接招商数据接口"
    except ValueError:
        message = "招商数据接口未返回有效 JSON"
    # 不回传外部异常正文，防止凭据或内部地址出现在对话中。
    logger.warning("investment.http.request_failed", endpoint=endpoint, reason=message)
    return {"status": "error", "data": None, "message": message}
