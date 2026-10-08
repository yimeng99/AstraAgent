"""AstraAgent Web API（FastAPI）。

启动::

    uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

API 端点（v1）：

* ``POST /api/v1/chat``                同步单轮
* ``POST /api/v1/chat/stream``         SSE 流式（前端主用）
* ``GET  /api/v1/threads``             列对话
* ``POST /api/v1/threads``             新建对话
* ``DELETE /api/v1/threads/{id}``      删除对话
* ``GET  /api/v1/threads/{id}/messages`` 历史消息
* ``POST /api/v1/upload``              上传图片 / 文档（multipart）
* ``GET  /api/v1/files/{file_id}``     回读已上传文件（按后缀给真实 Content-Type）
* ``GET  /api/v1/auth/me``              当前用户
* ``GET  /api/v1/health``              健康检查
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from api.middleware import register_middleware
from api.responses import ERROR_RESPONSES, register_exception_handlers
from api.routes import (
    approvals,
    chat,
    health,
    interactions,
    models,
    questions,
    sandbox,
    sandbox_files,
    threads,
    upload,
    user,
)
from api.run_store import setup as setup_runs
from api.stream_runs import shutdown_runs
from core import core_lifespan, load_app_config
from core.tracing import init_tracing, shutdown_tracing
from core.utils.logging import configure_logging, get_logger

# ── 日志 ────────────────────────────────────────
configure_logging(level="INFO", fmt="console")

logger = get_logger("api.main")


# ── 生命周期 ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api.startup.begin")
    # 挂载全局配置
    cfg = load_app_config()
    app.state.cfg = cfg
    init_tracing(cfg.tracing)
    try:
        async with core_lifespan(cfg) as agent:
            app.state.agent = agent
            # Web 执行依赖持久化运行记录；表不可用时不能宣称已就绪。
            # MCP / 沙箱仍由各自初始化边界隔离，不影响基础对话启动。
            await setup_runs()
            app.state.ready = True
            logger.info("api.startup.done", status="ready")
            try:
                yield
            finally:
                await shutdown_runs()
    finally:
        app.state.ready = False
        logger.info("api.shutdown.done")
        shutdown_tracing()


app = FastAPI(
    title="AstraAgent API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    responses=ERROR_RESPONSES,
)


register_exception_handlers(app)
register_middleware(app)


# ── 路由 ────────────────────────────────────────
app.include_router(approvals.router, prefix="/api/v1", tags=["approvals"])
app.include_router(questions.router, prefix="/api/v1", tags=["questions"])
app.include_router(interactions.router, prefix="/api/v1", tags=["interactions"])
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(models.router, prefix="/api/v1", tags=["models"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(threads.router, prefix="/api/v1", tags=["threads"])
app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(sandbox_files.router, prefix="/api/v1", tags=["sandbox-files"])
app.include_router(sandbox.router, prefix="/api/v1", tags=["sandbox"])
app.include_router(user.router, tags=["user"])


if __name__ == "__main__":
    logger.info("api.bootstrap", host="0.0.0.0", port=8000)
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, log_config=None)
