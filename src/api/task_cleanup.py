"""等待资源清理完成后再传播调用方取消。"""

import asyncio

__all__ = ["wait_for_cleanup"]


async def wait_for_cleanup(cleanup: asyncio.Task[None]) -> None:
    """只等待传入的清理任务；重复取消不会重建任务或中断资源释放。"""
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    cleanup.result()
    if cancelled:
        raise asyncio.CancelledError
