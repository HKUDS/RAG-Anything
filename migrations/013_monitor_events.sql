-- ══════════════════════════════════════════════════════════════════════════════
-- RAG-Anything 监控事件日志持久化
-- 迁移编号: 013_monitor_events
-- 目标数据库: PostgreSQL
-- 说明: 为 /api/monitor/logs 与 /api/monitor/status 提供跨重启保留的事件流水
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS monitor_events (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event       TEXT NOT NULL,
    user_id     INTEGER NOT NULL DEFAULT 0,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_monitor_events_created
    ON monitor_events(created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_monitor_events_user_created
    ON monitor_events(user_id, created_at DESC, id DESC);

COMMIT;
