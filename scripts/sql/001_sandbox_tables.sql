-- 用户 ID 必须全局唯一；运行时接入前不自动迁移或删除旧沙箱。
CREATE TABLE public.user_sandboxes (
    sandbox_id TEXT PRIMARY KEY CHECK (btrim(sandbox_id) <> ''), -- 沙箱 ID
    user_id TEXT NOT NULL UNIQUE CHECK (btrim(user_id) <> ''), -- 用户 ID
    volume_path TEXT UNIQUE CHECK (btrim(volume_path) <> ''), -- 宿主机完整挂载源路径；未挂载为 NULL
    disk_capacity_bytes BIGINT CHECK (disk_capacity_bytes > 0), -- 当前磁盘容量（字节），未知为空
    disk_used_bytes BIGINT CHECK (disk_used_bytes >= 0), -- 最近采集的使用量（字节），未知为空
    disk_resize_count INTEGER NOT NULL DEFAULT 0 CHECK (disk_resize_count >= 0) -- 成功扩容次数
);

COMMENT ON TABLE public.user_sandboxes IS '用户沙箱信息；尚未接入运行时';
COMMENT ON COLUMN public.user_sandboxes.user_id IS '系统内全局唯一的用户 ID';
COMMENT ON COLUMN public.user_sandboxes.sandbox_id IS 'OpenSandbox 返回的沙箱 ID，主键；创建成功取得 ID 后保存记录';
COMMENT ON COLUMN public.user_sandboxes.volume_path IS '宿主机完整挂载源路径；未挂载为 NULL，挂载时沙箱内路径为 /workspace';
COMMENT ON COLUMN public.user_sandboxes.disk_capacity_bytes IS '当前已确认容量，单位字节；未知为空，修改字段不会实际扩容';
COMMENT ON COLUMN public.user_sandboxes.disk_used_bytes IS '最近采集的已使用量，单位字节；未知为空，不代表实时值';
COMMENT ON COLUMN public.user_sandboxes.disk_resize_count IS '实际扩容成功后增加一次；失败和初次分配不计数';
