"""普通 JSON 接口的响应契约；SSE、文件和重定向保持原协议。"""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from core.human import HumanConflictError, HumanInputError
from core.sessions import ThreadAccessError
from core.utils.logging import get_logger

logger = get_logger(__name__)


class ResultCode(StrEnum):
    SUCCESS = "0"
    BAD_REQUEST = "400"
    UNAUTHORIZED = "401"
    FORBIDDEN = "403"
    NOT_FOUND = "404"
    METHOD_NOT_ALLOWED = "405"
    CONFLICT = "409"
    GONE = "410"
    PAYLOAD_TOO_LARGE = "413"
    UNSUPPORTED_MEDIA_TYPE = "415"
    VALIDATION_ERROR = "422"
    TOO_MANY_REQUESTS = "429"
    INTERNAL_ERROR = "500"
    NOT_IMPLEMENTED = "501"
    SERVICE_UNAVAILABLE = "503"


class ApiResult[T](BaseModel):
    code: str = ResultCode.SUCCESS
    message: str = "成功"
    data: T | None = None


def success[T](data: T | None = None) -> ApiResult[T]:
    return ApiResult(data=data)


def error_response(
    status_code: int, message: str, *, data: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiResult(code=str(status_code), message=message, data=data).model_dump(
            mode="json"
        ),
        headers=headers,
    )


ERROR_RESPONSES = {
    int(code): {"model": ApiResult[Any]} for code in ResultCode if code != ResultCode.SUCCESS
}


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return error_response(
        exc.status_code,
        exc.detail if isinstance(exc.detail, str) else "请求失败",
        headers=exc.headers,
    )


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # 不回显 input / ctx，校验失败的字段可能包含凭证或大段用户内容。
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return error_response(422, "请求参数不合法", data={"errors": errors})


async def human_error(request: Request, exc: Exception) -> JSONResponse:
    status = (
        404
        if isinstance(exc, ThreadAccessError)
        else 422
        if isinstance(exc, HumanInputError)
        else 409
    )
    return error_response(status, str(exc))


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("http.unhandled", path=request.url.path, error=type(exc).__name__)
    return error_response(500, "服务内部错误，请稍后重试")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    for exception in (ThreadAccessError, HumanInputError, HumanConflictError):
        app.add_exception_handler(exception, human_error)
    app.add_exception_handler(Exception, unexpected_error)
