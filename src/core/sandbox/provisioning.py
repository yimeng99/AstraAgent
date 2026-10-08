"""用户持久卷沙箱的查询、创建与恢复；调用方必须已取得用户数据库锁。"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import PurePosixPath, PureWindowsPath

from opensandbox import SandboxSync
from opensandbox.models.sandboxes import Host, SandboxFilter, Volume
from opensandbox.sync.manager import SandboxManagerSync

from core.config import PROJECT_ROOT
from core.sandbox.repository import get_user_sandbox, legacy_sandbox_id, save_user_sandbox
from core.sandbox.skills import skills_version, sync_skills


def build_volume_path(root: str, tenant_id: str, user_id: str) -> str:
    if not root or not user_id.strip():
        raise ValueError("需要配置 SANDBOX_VOLUME_ROOT 并提供用户 ID")
    path = PureWindowsPath(root) if PureWindowsPath(root).drive else PurePosixPath(root)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("SANDBOX_VOLUME_ROOT 必须是无上级跳转的绝对路径")
    return (
        path
        / "tenants"
        / hashlib.sha256(tenant_id.encode()).hexdigest()
        / "users"
        / hashlib.sha256(user_id.encode()).hexdigest()
    ).as_posix()


def sandbox_owner(path: str | None, context) -> str:
    # 无挂载时仍以租户与用户标记远程归属，不能使用空路径作为所有用户的共同键。
    identity = path if path is not None else repr(("unmounted", context.tenant_id, context.user_id))
    return hashlib.sha256(identity.encode()).hexdigest()[:48]


def get_or_create_sandbox(db, context, config):
    """先绑定数据库再初始化；失败保留已创建环境，下次连接时重试初始化。"""
    path = (
        build_volume_path(config.volume_root, context.tenant_id, context.user_id)
        if config.volume_enabled
        else None
    )
    record = get_user_sandbox(db, context.user_id)
    if record and record["volume_path"] != path:
        raise PermissionError("已有沙箱挂载方式或位置与当前配置不一致，请先迁移；不会自动重建")
    connection = config.connection_config()
    # OpenSandbox metadata 遵循标签限制，值最多 63 字符。
    owner = sandbox_owner(path, context)
    metadata = {"astra_volume_owner": owner}
    control = SandboxManagerSync.create(connection_config=connection)
    sandbox = None
    try:
        if record:
            info = control.get_sandbox_info(record["sandbox_id"])
        else:
            scope = f"{context.tenant_id}:{context.user_id}"
            legacy_id = legacy_sandbox_id(
                PROJECT_ROOT / "workspace" / "sandbox-state.sqlite3",
                connection.get_base_url(),
                scope,
            )
            if legacy_id:
                # 仅原地接管已暂停的旧环境；不删除容器，不假装已挂载新数据卷。
                if config.volume_enabled:
                    raise RuntimeError("旧沙箱未挂载数据卷，请先迁移文件后再启用挂载")
                legacy = control.get_sandbox_info(legacy_id)
                expected = hashlib.sha256(scope.encode()).hexdigest()[:48]
                if (legacy.metadata or {}).get("astra_scope") != expected:
                    raise PermissionError("旧沙箱归属校验失败")
                if legacy.status.state.upper() != "PAUSED" or legacy.expires_at is not None:
                    raise RuntimeError("迁移旧沙箱需要先暂停环境，并确认没有自动过期时间")
                if (legacy.metadata or {}).get("astra_active_operation"):
                    raise RuntimeError("旧沙箱仍有未确认结束的操作，拒绝迁移")
                bound_owner = (legacy.metadata or {}).get("astra_volume_owner")
                if bound_owner and bound_owner != owner:
                    raise PermissionError("旧沙箱已绑定其他归属")
                control.patch_sandbox_metadata(legacy_id, metadata)
                save_user_sandbox(db, context.user_id, legacy_id, None)
                record = get_user_sandbox(db, context.user_id)
            # 创建完成但数据库写入失败时，重试优先找回原环境。
            if record:
                info = control.get_sandbox_info(record["sandbox_id"])
            else:
                found = control.list_sandbox_infos(SandboxFilter(metadata=metadata, page_size=2))
                if found.pagination.total_items > 1:
                    raise RuntimeError("同一用户存在多个远程沙箱，需要核对后再使用")
                info = found.sandbox_infos[0] if found.sandbox_infos else None
        if info is None:
            sandbox = SandboxSync.create(
                config.image,
                connection_config=connection,
                timeout=None,
                resource=config.resource(),
                metadata=metadata,
                volumes=[
                    Volume(name="user-workspace", host=Host(path=path), mount_path="/workspace")
                ]
                if path is not None
                else None,
                extensions={"bootstrap.execd.isolation": "enable"},
            )
            save_user_sandbox(db, context.user_id, sandbox.id, path)
        else:
            if (info.metadata or {}).get("astra_volume_owner") != owner:
                raise PermissionError("远程沙箱归属标识不一致，拒绝连接")
            if (info.metadata or {}).get("astra_active_operation"):
                raise RuntimeError("原沙箱操作未确认结束，需要恢复处理；不会自动并发执行")
            if info.expires_at is not None:
                raise RuntimeError("用户沙箱必须使用手动清理模式")
            if not record:
                save_user_sandbox(db, context.user_id, info.id, path)
            remote_state = info.status.state.upper()
            if remote_state == "PAUSED":
                sandbox = SandboxSync.resume(info.id, connection_config=connection)
            elif remote_state == "RUNNING":
                sandbox = SandboxSync.connect(info.id, connection_config=connection)
            else:
                raise RuntimeError(f"原沙箱状态为 {remote_state}，暂时无法使用，不会重新创建")
        version = skills_version()
        if info is None or (info.metadata or {}).get("astra_skills_version") != version:
            sync_skills(sandbox)
            control.patch_sandbox_metadata(sandbox.id, {"astra_skills_version": version})
        token = uuid.uuid4().hex
        # 数据库断连会释放 advisory lock，但不代表远程命令结束。
        # 保留远端占用标记使下一实例拒绝盲目接管；完整故障恢复由后续阶段实现。
        db.execute("SELECT 1")
        control.patch_sandbox_metadata(sandbox.id, {"astra_active_operation": token})
        return sandbox, token
    except BaseException:
        if sandbox is not None:
            sandbox.close()
        raise
    finally:
        control.close()


def finish_user_operation(db, config, sandbox_id: str, token: str) -> None:
    db.execute("SELECT 1")
    control = SandboxManagerSync.create(connection_config=config.connection_config())
    try:
        info = control.get_sandbox_info(sandbox_id)
        if (info.metadata or {}).get("astra_active_operation") != token:
            raise RuntimeError("沙箱操作持有标识已变化，拒绝释放其他操作")
        control.patch_sandbox_metadata(sandbox_id, {"astra_active_operation": None})
    finally:
        control.close()
