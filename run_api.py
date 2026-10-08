"""单进程 API 入口：长任务不随源码改动重启，也可在 IDE 中逐步调试。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="AstraAgent API 服务（无热重载）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # 直接运行文件时也能解析 src 下的包，不依赖 IDE 的 Sources Root 设置。
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config("api.main:app", host=args.host, port=args.port, log_config=None)
    )
    # 不让源码变更取消长任务；Windows psycopg 必须显式使用 Selector。
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    asyncio.run(server.serve(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
