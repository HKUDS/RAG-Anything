-- ============================================================================
-- Migration: 011_unified_case_library.sql
-- Description: Merge fault_cases + process_documents into unified `cases` table
--              with case_type discriminator ('fault' | 'process').
-- Date: 2026-07-03
-- ============================================================================

BEGIN;

-- =============================================================================
-- 1. Create unified cases table
-- =============================================================================

CREATE TABLE IF NOT EXISTS cases (
    id                    VARCHAR(50) PRIMARY KEY,
    title                 VARCHAR(500) NOT NULL,
    case_type             VARCHAR(20) NOT NULL DEFAULT 'fault',  -- 'fault' | 'process'

    -- Fault-case-specific fields (nullable for process rows)
    equipment_type        VARCHAR(200),
    fault_category        VARCHAR(200),
    phenomenon            TEXT,
    root_cause            TEXT,
    troubleshooting_steps JSONB DEFAULT '[]',
    preventive_measures   JSONB DEFAULT '[]',
    severity              VARCHAR(20) DEFAULT 'medium',
    occurrence_count      INTEGER DEFAULT 0,

    -- Process-specific fields (nullable for fault rows)
    category              VARCHAR(100),          -- auto-classified process category
    parameters            JSONB DEFAULT '[]',    -- extracted process parameters
    file_path             TEXT DEFAULT '',
    file_size_bytes       BIGINT DEFAULT 0,
    text_preview          TEXT DEFAULT '',        -- first 500 chars of full_text
    full_text             TEXT DEFAULT '',        -- complete process document text

    -- Common
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_cases_case_type ON cases(case_type);
CREATE INDEX IF NOT EXISTS idx_cases_category ON cases(category);
CREATE INDEX IF NOT EXISTS idx_cases_equipment_type ON cases(equipment_type);
CREATE INDEX IF NOT EXISTS idx_cases_fault_category ON cases(fault_category);
CREATE INDEX IF NOT EXISTS idx_cases_severity ON cases(severity);
CREATE INDEX IF NOT EXISTS idx_cases_created_at ON cases(created_at DESC);

-- Full-text search index for process document text
CREATE INDEX IF NOT EXISTS idx_cases_full_text_fts
    ON cases USING gin(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(full_text, '')));

-- Auto-update updated_at trigger
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_cases_updated_at'
    ) THEN
        CREATE TRIGGER trg_cases_updated_at
            BEFORE UPDATE ON cases
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;


-- =============================================================================
-- 2. Migrate data from fault_cases → cases (case_type='fault')
-- =============================================================================

INSERT INTO cases (id, title, case_type,
    equipment_type, fault_category, phenomenon, root_cause,
    troubleshooting_steps, preventive_measures, severity, occurrence_count,
    created_at, updated_at)
SELECT
    id, title, 'fault',
    equipment_type, fault_category, phenomenon, root_cause,
    troubleshooting_steps, preventive_measures, severity, occurrence_count,
    created_at, updated_at
FROM fault_cases
ON CONFLICT (id) DO NOTHING;


-- =============================================================================
-- 3. Migrate data from process_documents → cases (case_type='process')
-- =============================================================================

INSERT INTO cases (id, title, case_type,
    category, parameters, file_path, file_size_bytes,
    text_preview, full_text, created_at, updated_at)
SELECT
    id, title, 'process',
    category, parameters, file_path, file_size_bytes,
    text_preview, full_text, ingested_at, updated_at
FROM process_documents
ON CONFLICT (id) DO NOTHING;


-- =============================================================================
-- 4. Verification — row counts should match
-- =============================================================================

-- SELECT 'fault_cases' AS source, count(*) FROM fault_cases
-- UNION ALL
-- SELECT 'cases (fault)', count(*) FROM cases WHERE case_type = 'fault'
-- UNION ALL
-- SELECT 'process_documents', count(*) FROM process_documents
-- UNION ALL
-- SELECT 'cases (process)', count(*) FROM cases WHERE case_type = 'process';


-- =============================================================================
-- 5. Drop old tables (uncomment after verification)
-- =============================================================================

-- DROP TABLE IF EXISTS fault_cases CASCADE;
-- DROP TABLE IF EXISTS process_documents CASCADE;

COMMIT;
