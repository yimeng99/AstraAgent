"""标识符生成。

集中一处，方便以后换成 ULID / 带前缀的短 ID，而不用逐个改调用点。
"""

from __future__ import annotations

import uuid

__all__ = ["get_uuid"]


def get_uuid() -> str:
    """生成一个 UUID4 字符串（带连字符）。

    Returns:
        形如 ``"3f2504e0-4f89-41d3-9a0c-0305e82c3301"`` 的随机标识符。
    """
    return str(uuid.uuid4())
