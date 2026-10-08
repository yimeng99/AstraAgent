"""Core 包结构化日志。

structlog + JSON 输出，配置简单。

要点：把同一套 processor 链路接进 stdlib 的 ``Formatter``（``logging.basicConfig``），
让 uvicorn 的访问日志、第三方库（urllib / requests / opensandbox）的 traceback
**都按同一种格式输出**（时间戳、字段、颜色）—— 否则同一个进程里看着
时间 + 级别齐全，又空 + 没级别 / 没颜色混合打印，调试极其痛苦。
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog

__all__ = ["LevelFormat", "configure_logging", "get_logger"]

LevelFormat = Literal["json", "console"]


def _trace_context(logger, method_name, event_dict):
    # 延迟导入避免 tracing 初始化时与日志模块循环依赖。
    from core.tracing import trace_fields

    event_dict.update(trace_fields())
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    fmt: LevelFormat = "console",
) -> None:
    """配置全局结构化日志。

    Args:
        level: 日志级别（DEBUG / INFO / WARNING / ERROR）。
        fmt: 输出格式。``"json"`` 用于生产；``"console"`` 用于本地开发。
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # 应用和第三方日志统一交给 root handler，避免各层处理器重复输出。
    pre: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _trace_context,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        foreign_pre_chain=pre,
        keep_exc_info=False,  # format_exc_info 已把 exc_info 收成 exception 字符串
    )
    # ``force=True`` 覆盖任何已有 handler（uvicorn 自己装了一个 basicConfig-style）。
    root_handler = logging.StreamHandler(sys.stdout)
    root_handler.setFormatter(formatter)
    logging.basicConfig(level=log_level, handlers=[root_handler], force=True)

    # Uvicorn 自带 handler；保留它再开启 propagate 会在父 logger 重复输出。
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.lifespan"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
        lg.setLevel(log_level)

    # 未配置 handler 且禁止传播的第三方 logger 也使用相同的异常格式。
    logging.lastResort = root_handler
    # HTTP 中间件已有带 request_id 的访问记录，避免 Uvicorn 再打印一份。
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(
            logging.WARNING if log_level > logging.DEBUG else log_level
        )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *pre,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """获取绑定到 ``name`` 的 logger（首选模块级使用）。"""
    return structlog.get_logger(name)
