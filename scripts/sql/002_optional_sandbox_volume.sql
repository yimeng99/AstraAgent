-- 全局 SANDBOX_VOLUME_ENABLED 控制新沙箱是否挂载；不改动已有沙箱和数据。
BEGIN;
ALTER TABLE public.user_sandboxes ALTER COLUMN volume_path DROP NOT NULL;
COMMENT ON COLUMN public.user_sandboxes.volume_path IS '宿主机完整挂载源路径；未挂载为 NULL，挂载时沙箱内路径为 /workspace';
COMMIT;
