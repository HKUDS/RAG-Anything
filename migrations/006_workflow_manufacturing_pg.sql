-- ══════════════════════════════════════════════════════════════════════════════
-- RAG-Anything 工作流 + 制造知识库数据 — 建表迁移
-- 迁移编号: 006_workflow_manufacturing_pg
-- 目标数据库: PostgreSQL
-- 说明: 将制造模块（Manufacturing）的工作流定义、执行记录、故障案例、
--       工艺文档和仪表盘查询日志从 JSON 文件迁移到 PG 表
--
-- 【本迁移创建的表】
--   workflow_definitions  工作流定义（名称、步骤、触发条件、JSON 配置）
--   workflow_runs         工作流执行记录（状态、起止时间、结果、错误信息）
--   fault_cases           故障案例库（故障描述、根因分析、解决方案、分类标签）
--   process_documents     工艺文档库（SOP、工艺卡片、操作手册、元数据）
--   dashboard_query_log   仪表盘查询日志（查询统计、性能监控、使用频率分析）
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- =============================================================================
-- 1. Workflow Definitions — replaces ./workflows/{id}.json
-- =============================================================================
-- Access Patterns:
--   LIST:        SELECT ... ORDER BY updated_at DESC
--   READ single: SELECT WHERE id = $1
--   CREATE:      INSERT INTO workflow_definitions (...)
--   UPDATE:      UPDATE SET ... WHERE id = $1
--   DELETE:      DELETE WHERE id = $1
--               (CASCADE deletes all related runs)

CREATE TABLE IF NOT EXISTS workflow_definitions (
    id          VARCHAR(50) PRIMARY KEY,
    user_id     INTEGER NOT NULL DEFAULT 0,
    name        VARCHAR(200) NOT NULL DEFAULT '未命名工作流',
    definition  JSONB NOT NULL DEFAULT '{"nodes": [], "edges": []}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_def_user_updated
    ON workflow_definitions(user_id, updated_at DESC);


-- =============================================================================
-- 2. Workflow Runs — replaces ./workflows/runs/{run_id}.json
-- =============================================================================
-- CASCADE DELETE: when a workflow is deleted, all its runs are removed.

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id          VARCHAR(50) PRIMARY KEY,
    workflow_id     VARCHAR(50) NOT NULL
                    REFERENCES workflow_definitions(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL DEFAULT 0,
    workflow_name   VARCHAR(200) NOT NULL DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'running',
    node_results    JSONB NOT NULL DEFAULT '[]',
    final_output    TEXT NOT NULL DEFAULT '',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_wf_runs_workflow
    ON workflow_runs(workflow_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_wf_runs_user
    ON workflow_runs(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_wf_runs_status
    ON workflow_runs(status) WHERE status != 'completed';


-- =============================================================================
-- 3. Fault Cases — replaces data/manufacturing_kb/fault_cases/cases.json
-- =============================================================================

CREATE TABLE IF NOT EXISTS fault_cases (
    id                    VARCHAR(50) PRIMARY KEY,
    title                 VARCHAR(500) NOT NULL,
    equipment_type        VARCHAR(200) NOT NULL DEFAULT '',
    fault_category        VARCHAR(200) NOT NULL DEFAULT '',
    phenomenon            TEXT NOT NULL DEFAULT '',
    root_cause            TEXT NOT NULL DEFAULT '',
    troubleshooting_steps JSONB NOT NULL DEFAULT '[]',
    preventive_measures   JSONB NOT NULL DEFAULT '[]',
    severity              VARCHAR(20) NOT NULL DEFAULT 'medium',
    occurrence_count      INTEGER NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fault_cases_equipment
    ON fault_cases(equipment_type);
CREATE INDEX IF NOT EXISTS idx_fault_cases_category
    ON fault_cases(fault_category);
CREATE INDEX IF NOT EXISTS idx_fault_cases_severity
    ON fault_cases(severity);

-- Trigger: auto-update updated_at
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_fault_cases_updated_at'
    ) THEN
        CREATE TRIGGER trg_fault_cases_updated_at
            BEFORE UPDATE ON fault_cases
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;


-- =============================================================================
-- 4. Process Documents — replaces data/manufacturing_kb/processes/_index.json
-- =============================================================================

CREATE TABLE IF NOT EXISTS process_documents (
    id              VARCHAR(50) PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    category        VARCHAR(100) NOT NULL DEFAULT 'general',
    parameters      JSONB NOT NULL DEFAULT '[]',
    file_path       TEXT NOT NULL DEFAULT '',
    file_size_bytes BIGINT NOT NULL DEFAULT 0,
    text_preview    TEXT NOT NULL DEFAULT '',
    full_text       TEXT NOT NULL DEFAULT '',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_process_docs_category
    ON process_documents(category);
-- Full-text search index for Chinese text (uses 'simple' config for mixed content)
CREATE INDEX IF NOT EXISTS idx_process_docs_fts
    ON process_documents
    USING gin(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(full_text, '')));

-- Trigger: auto-update updated_at
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_process_documents_updated_at'
    ) THEN
        CREATE TRIGGER trg_process_documents_updated_at
            BEFORE UPDATE ON process_documents
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;


-- =============================================================================
-- 5. Dashboard Query Log — replaces data/manufacturing_kb/dashboard/query_log.json
-- =============================================================================
-- Append-only time-series data. Partition by month for >1M rows.
-- Keeping single table for now (<100K typical in education deployment).

CREATE TABLE IF NOT EXISTS dashboard_query_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL DEFAULT '',
    institution_id  TEXT NOT NULL DEFAULT '',
    query           TEXT NOT NULL DEFAULT '',
    query_type      VARCHAR(50) NOT NULL DEFAULT 'qa',
    response_ms     DOUBLE PRECISION NOT NULL DEFAULT 0,
    kb_name         VARCHAR(255) NOT NULL DEFAULT 'default',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dql_created
    ON dashboard_query_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dql_user_time
    ON dashboard_query_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dql_kb
    ON dashboard_query_log(kb_name, created_at DESC);

-- =============================================================================
-- Verification
-- =============================================================================
-- \dt+                              — list all tables
-- SELECT * FROM workflow_definitions ORDER BY updated_at DESC;
-- SELECT * FROM workflow_runs WHERE workflow_id = '...' ORDER BY started_at DESC;
-- SELECT * FROM fault_cases ORDER BY created_at DESC;
-- SELECT * FROM process_documents ORDER BY ingested_at DESC;
-- SELECT count(*) FROM dashboard_query_log;

COMMIT;
