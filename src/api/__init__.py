"""AstraAgent HTTP API 包（FastAPI）。

子模块：

* :mod:`api.routes` —— 路由（chat / threads / health）
* :mod:`api.schemas` —— Pydantic 请求 / 响应模型
* :mod:`api.deps`    —— FastAPI Depends（注入 agent / thread store / 当前用户）
* :mod:`api.sse`     —— SSE 响应助手
"""

from __future__ import annotations

__all__: list[str] = []
