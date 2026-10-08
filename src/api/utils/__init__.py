"""API 层通用工具。

* :mod:`api.utils.ids` —— 标识符生成（thread_id / request_id 等）
"""

from __future__ import annotations

from api.utils.ids import get_uuid

__all__ = ["get_uuid"]
