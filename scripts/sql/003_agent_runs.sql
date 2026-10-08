-- 运行归属由 PostgreSQL 会话锁维持；连接消失后，running 才可以被识别为 interrupted。
-- 不保存用户 token。恢复时重新取得当前请求的身份与权限。
CREATE TABLE IF NOT EXISTS agent_runs (
    thread_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE agent_runs IS '会话最近一次运行状态，配合 PG 会话锁识别进程退出';
COMMENT ON COLUMN agent_runs.status IS 'running/completed/waiting/failed/stopped/interrupted';
