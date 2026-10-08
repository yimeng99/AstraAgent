"""模型超时在单次模型调用内重试，避免重跑已完成的工具。"""

import httpx
from langchain.agents.middleware import ModelRetryMiddleware
from openai import APITimeoutError


def model_timeout_retry(provider: str) -> ModelRetryMiddleware:
    """仅重试已选 provider 的超时；鉴权、参数和程序错误直接上报。"""
    timeout_types: tuple[type[Exception], ...] = (
        TimeoutError,
        httpx.TimeoutException,
        APITimeoutError,
    )
    if provider == "anthropic":
        from anthropic import APITimeoutError as AnthropicTimeoutError

        timeout_types += (AnthropicTimeoutError,)
    return ModelRetryMiddleware(
        max_retries=3,
        retry_on=timeout_types,
        on_failure="error",
        initial_delay=1,
        backoff_factor=2,
        max_delay=4,
        jitter=False,
    )
