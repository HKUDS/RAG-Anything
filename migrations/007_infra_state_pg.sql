-- =============================================================================
-- RAG-Anything Phase 4 PG Migration: Infrastructure State
-- Migration: 007_infra_state_pg
-- Target: PostgreSQL (existing raganything-pg container)
-- Description:
--   1. processing_tasks — replaces in-memory dict for cross-worker visibility
--   2. embedding_cache  — replaces .embedding_cache.json for cross-worker sharing
--   3. Recovery lock already uses pg_advisory_lock() (no table needed)
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. Processing Tasks — cross-worker document processing state
-- =============================================================================
-- Replaces: in-memory `processing_tasks: dict[str, dict]` in state_service.py
--
-- Each row tracks one file being processed. Workers update progress/phase/status
-- in real-time; the frontend polls GET /api/upload/status/{task_id} to render
-- progress bars. This table enables:
--   - Cross-worker visibility (all workers see the same task state)
--   - Crash recovery (stuck tasks can be detected and re-queued)
--   - Audit trail (who uploaded what, when, with which parser/strategy)

CREATE TABLE IF NOT EXISTS processing_tasks (
    task_id         VARCHAR(64) PRIMARY KEY,       -- UUID-style task identifier
    kb_name         VARCHAR(255) NOT NULL DEFAULT 'default',
    file_name       VARCHAR(500) NOT NULL DEFAULT '',
    file_hash       VARCHAR(32) NOT NULL DEFAULT '',  -- SHA256[:16] for dedup
    user_id         INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
                    -- pending → processing → completed | failed
    progress        SMALLINT NOT NULL DEFAULT 0,      -- 0-100
    phase           VARCHAR(50) NOT NULL DEFAULT '',   -- parsing|chunking|embedding|graph
    phase_status    VARCHAR(50) NOT NULL DEFAULT '',
    chunking_strategy VARCHAR(50) NOT NULL DEFAULT '',
    error_message   TEXT NOT NULL DEFAULT '',
    message         TEXT NOT NULL DEFAULT '',          -- human-readable status msg
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pt_status ON processing_tasks(status);
CREATE INDEX IF NOT EXISTS idx_pt_kb ON processing_tasks(kb_name, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pt_user ON processing_tasks(user_id, updated_at DESC);


-- =============================================================================
-- 2. Embedding Cache — cross-worker shared embedding cache
-- =============================================================================
-- Replaces: per-KB .embedding_cache.json files
--
-- Keys: MD5(text || model_name), same as the JSON file cache.
-- Benefits:
--   - Cross-worker sharing: Worker A's embedded text is cached for Worker B
--   - No file I/O on the hot path (asyncpg pool is already warm)
--   - Natural TTL via optional cleanup of old entries
--
-- Performance note: PG lookup adds ~1ms latency vs ~0.01ms for local JSON.
-- The trade-off is worthwhile because:
--   - Cache hits avoid an embedding API call (~200ms), so net saving is 199ms
--   - Shared cache means higher hit rate, so more API calls avoided

CREATE TABLE IF NOT EXISTS embedding_cache (
    cache_key   TEXT PRIMARY KEY,                     -- MD5(text || model)
    model       VARCHAR(200) NOT NULL,
    embedding   double precision[] NOT NULL,           -- float32 vector as PG array
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hit_count   INTEGER NOT NULL DEFAULT 0             -- for LRU eviction decisions
);

CREATE INDEX IF NOT EXISTS idx_ec_model ON embedding_cache(model);
-- Partial index for low-hit entries (eviction candidates)
CREATE INDEX IF NOT EXISTS idx_ec_hit ON embedding_cache(hit_count)
    WHERE hit_count < 10;

-- Helper: upsert with hit_count increment
CREATE OR REPLACE FUNCTION embedding_cache_upsert(
    p_key       TEXT,
    p_model     VARCHAR(200),
    p_embedding double precision[]
) RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO embedding_cache (cache_key, model, embedding, hit_count)
    VALUES (p_key, p_model, p_embedding, 1)
    ON CONFLICT (cache_key) DO UPDATE SET
        hit_count = embedding_cache.hit_count + 1;
END;
$$;

-- Helper: evict oldest/lowest-hit entries when over cap
CREATE OR REPLACE FUNCTION embedding_cache_evict(max_entries INTEGER)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    excess INTEGER;
    deleted_count INTEGER;
BEGIN
    SELECT count(*) - max_entries INTO excess FROM embedding_cache;
    IF excess <= 0 THEN
        RETURN 0;
    END IF;
    -- Delete lowest-hit entries first, then oldest
    DELETE FROM embedding_cache
    WHERE cache_key IN (
        SELECT cache_key FROM embedding_cache
        ORDER BY hit_count ASC, created_at ASC
        LIMIT excess
    );
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

COMMIT;
