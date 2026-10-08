"""PostgreSQL 归属记录与跨实例用户锁；SQLite 仅用于阻止遗漏旧数据。"""

import hashlib
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def legacy_sandbox_id(path: Path, service: str, scope: str) -> str | None:
    if not path.exists():
        return None
    # 只读打开，不能再创建或更新第二套归属记录。
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute(
            "SELECT sandbox_id FROM sandboxes WHERE service = ? AND scope = ?",
            (service, scope),
        ).fetchone()
        return row[0] if row else None


def get_user_sandbox(db, user_id: str) -> dict | None:
    return db.execute(
        "SELECT * FROM public.user_sandboxes WHERE user_id = %s", (user_id,)
    ).fetchone()


def save_user_sandbox(db, user_id: str, sandbox_id: str, volume_path: str | None) -> None:
    # 容量和使用量尚未测量，不能把宿主机总容量冒充用户配额。
    db.execute(
        "INSERT INTO public.user_sandboxes (user_id, sandbox_id, volume_path) VALUES (%s, %s, %s)",
        (user_id, sandbox_id, volume_path),
    )


def lock_user(database_url: str, user_id: str, timeout_seconds: float):
    """跨实例串行访问；连接交给调用方关闭，关闭即释放会话级 advisory lock。"""
    lock_id = int.from_bytes(
        hashlib.sha256(("astra-sandbox:" + user_id).encode()).digest()[:8], signed=True
    )
    db = psycopg.connect(database_url, autocommit=True, row_factory=dict_row, connect_timeout=10)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if db.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (lock_id,)).fetchone()[
                "acquired"
            ]:
                return db
            if time.monotonic() >= deadline:
                raise TimeoutError("用户沙箱正在使用中，请稍后重试")
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    except BaseException:
        db.close()
        raise
