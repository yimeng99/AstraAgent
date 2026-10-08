"""统一会话标识与所有权规则，拒绝跨用户访问 checkpoint。"""

from __future__ import annotations

import re
import uuid

from core.exceptions import AstraAgentError

_THREAD = re.compile(
    r"^(.+)-([0-9a-f]{8}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


class ThreadAccessError(AstraAgentError):
    """统一拒绝未知归属及跨用户会话，不泄露会话是否存在。"""


def new_thread_id(user_id: str) -> str:
    return f"{user_id}-{uuid.uuid4().hex[:8]}"


def owned_by_thread_id(thread_id: str, user_id: str) -> bool:
    # 完整解析 owner，防止 alice 同时匹配 alice-team 的会话。
    match = _THREAD.fullmatch(thread_id)
    return bool(user_id and match and match.group(1) == user_id)


def assert_thread_owner(thread_id: str, user_id: str) -> None:
    if not owned_by_thread_id(thread_id, user_id):
        raise ThreadAccessError("对话不存在")
