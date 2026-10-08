"""保留本机已有的 bwrap 修复，仅隔离扩展启用时添加 NET_ADMIN。"""

from pathlib import Path

import opensandbox_server

path = Path(opensandbox_server.__file__).parent / "services/docker/docker_service.py"
source = path.read_text(encoding="utf-8")
# 私有网络的 loopback 配置需要 NET_ADMIN；模型进程仍在 strict profile 中降权。
changes = {
    '                cap_add.add("SYS_ADMIN")': (
        '                cap_add.update({"SYS_ADMIN", "NET_ADMIN"})\n'
        '                cap_drop = set(host_config_kwargs.get("cap_drop") or [])\n'
        '                cap_drop.difference_update({"SYS_ADMIN", "NET_ADMIN"})\n'
        '                host_config_kwargs["cap_drop"] = sorted(cap_drop)'
    ),
}
for old, new in changes.items():
    if source.count(old) != 1:
        raise RuntimeError(f"OpenSandbox 隔离分支已变化，请复核补丁：{old}")
    source = source.replace(old, new)
path.write_text(source, encoding="utf-8")
