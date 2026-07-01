-- ══════════════════════════════════════════════════════════════════════════════
-- RAG-Anything 制造模块配置 + 监控数据 — 建表迁移
-- 迁移编号: 008_manufacturing_config_pg
-- 目标数据库: PostgreSQL
-- 说明: 将制造模块的版权审计、运维指标、告警和部署配置从 JSON/内存迁移到 PG 表
--
-- 【本迁移创建的表】
--   copyright_audit_log  版权审计日志（文档版权审查记录、风险等级、处理结果）
--   ops_metrics          运维指标数据（CPU/内存/磁盘/请求量等时序数据）
--   ops_alerts           运维告警记录（告警规则触发、级别、通知状态，重启后保留）
--   institution_configs  机构部署配置（学校/企业的个性化部署参数）
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- =============================================================================
-- 1. Copyright Audit Log — replaces copyright_audit.json
-- =============================================================================
-- Access Patterns:
--   APPEND:  INSERT INTO copyright_audit_log (...) — log state transitions
--   READ:    SELECT WHERE resource_id = $1 — audit trail lookup
--   LIST:    SELECT ... ORDER BY created_at DESC — full audit log

CREATE TABLE IF NOT EXISTS copyright_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    resource_id     VARCHAR(255) NOT NULL,
    from_status     VARCHAR(50) NOT NULL,
    to_status       VARCHAR(50) NOT NULL,
    operator        VARCHAR(255) NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_copyright_audit_resource
    ON copyright_audit_log(resource_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_copyright_audit_created
    ON copyright_audit_log(created_at DESC);


-- =============================================================================
-- 2. Ops Metrics — replaces metrics_{month}.json
-- =============================================================================
-- Access Patterns:
--   APPEND:  INSERT INTO ops_metrics (...) — record single request
--   READ:    SELECT WHERE month = $1 — monthly report generation
--   AGG:     SELECT count(*), avg(response_ms), ... WHERE month = $1

CREATE TABLE IF NOT EXISTS ops_metrics (
    id              BIGSERIAL PRIMARY KEY,
    endpoint        VARCHAR(500) NOT NULL,
    response_ms     DOUBLE PRECISION NOT NULL,
    status_code     INTEGER NOT NULL DEFAULT 200,
    month           VARCHAR(7) NOT NULL,       -- 'YYYY-MM'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_metrics_month
    ON ops_metrics(month, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_metrics_endpoint_month
    ON ops_metrics(endpoint, month);


-- =============================================================================
-- 3. Ops Alerts — replaces in-memory alerts (persists across restarts)
-- =============================================================================
-- Access Patterns:
--   CREATE:  INSERT INTO ops_alerts (...) — raise new alert
--   LIST:    SELECT WHERE resolved_at IS NULL — active alerts
--   UPDATE:  UPDATE SET resolved_at = NOW() WHERE id = $1 — resolve alert

CREATE TABLE IF NOT EXISTS ops_alerts (
    id              BIGSERIAL PRIMARY KEY,
    alert_type      VARCHAR(100) NOT NULL,
    message         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ops_alerts_active
    ON ops_alerts(created_at DESC) WHERE resolved_at IS NULL;


-- =============================================================================
-- 4. Institution Configs — replaces config/deployments.json
-- =============================================================================
-- Access Patterns:
--   CREATE:  INSERT INTO institution_configs (...)
--   READ:    SELECT WHERE institution_id = $1
--   UPDATE:  UPDATE SET ... WHERE institution_id = $1
--   DELETE:  DELETE WHERE institution_id = $1
--   LIST:    SELECT institution_id, institution_name, ...

CREATE TABLE IF NOT EXISTS institution_configs (
    institution_id          VARCHAR(255) PRIMARY KEY,
    institution_name        VARCHAR(500) NOT NULL,
    institution_type        VARCHAR(50) NOT NULL DEFAULT 'school',
    enabled_tracks          JSONB NOT NULL DEFAULT '[]',
    enabled_knowledge_types JSONB NOT NULL DEFAULT '[]',
    answer_style            VARCHAR(50) NOT NULL DEFAULT 'detailed',
    citation_style          VARCHAR(50) NOT NULL DEFAULT 'inline',
    language                VARCHAR(20) NOT NULL DEFAULT 'zh-CN',
    max_concurrent_users    INTEGER NOT NULL DEFAULT 50,
    rate_limit_per_minute   INTEGER NOT NULL DEFAULT 30,
    allow_code_parser       BOOLEAN NOT NULL DEFAULT true,
    allow_video_locator     BOOLEAN NOT NULL DEFAULT true,
    allow_fault_diagnosis   BOOLEAN NOT NULL DEFAULT true,
    theme                   VARCHAR(50) NOT NULL DEFAULT 'default',
    custom_logo_url         TEXT NOT NULL DEFAULT '',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Trigger: auto-update updated_at
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_institution_configs_updated_at'
    ) THEN
        CREATE TRIGGER trg_institution_configs_updated_at
            BEFORE UPDATE ON institution_configs
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;


-- =============================================================================
-- Verification
-- =============================================================================
-- SELECT count(*) FROM copyright_audit_log;
-- SELECT * FROM ops_alerts WHERE resolved_at IS NULL;
-- SELECT * FROM ops_metrics WHERE month = to_char(NOW(), 'YYYY-MM') LIMIT 10;
-- SELECT * FROM institution_configs;

COMMIT;
