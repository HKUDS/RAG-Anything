BEGIN;

-- User choices are sparse JSONB overrides.  They are intentionally separate
-- from the generic settings table, which also contains deployment/JWT state.
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    revision BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform_settings (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    schema_version INTEGER NOT NULL DEFAULT 1,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    revision BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS task_settings_snapshots (
    task_id VARCHAR(64) PRIMARY KEY,
    user_id INTEGER NOT NULL,
    revision BIGINT NOT NULL,
    fingerprint VARCHAR(128) NOT NULL,
    profile_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    settings JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_quota_leases (
    id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL,
    task_id VARCHAR(64) NOT NULL,
    lease_owner VARCHAR(128) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, task_id, lease_owner)
);
CREATE INDEX IF NOT EXISTS idx_user_quota_leases_active
    ON user_quota_leases(user_id, expires_at);

-- The pre-existing vision service used runtime DDL.  Formalize the table and
-- preserve existing VLM selections for migration into user_settings.
CREATE TABLE IF NOT EXISTS user_model_preferences (
    user_id INTEGER PRIMARY KEY,
    vision_vlm_profile_id VARCHAR(255),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Preserve a legacy VLM choice as the sparse override used by the new
-- resolver.  Existing explicit user-settings rows always win; the migration
-- only fills a missing models section.
INSERT INTO user_settings (user_id, settings, revision)
SELECT
    user_id,
    jsonb_build_object('models', jsonb_build_object('vlm_profile_id', vision_vlm_profile_id)),
    1
FROM user_model_preferences
WHERE vision_vlm_profile_id IS NOT NULL AND btrim(vision_vlm_profile_id) <> ''
ON CONFLICT (user_id) DO UPDATE
SET settings = jsonb_set(
        user_settings.settings,
        '{models}',
        EXCLUDED.settings -> 'models',
        true
    ),
    revision = user_settings.revision + 1,
    updated_at = NOW()
WHERE NOT (user_settings.settings ? 'models');

-- ``config/runtime_settings.json`` shipped with max_async=7.  It is a
-- startup-only compatibility input now, so seed its value into the typed,
-- durable platform policy instead of retaining a mutable runtime file as the
-- source of truth.  Empty allow-lists mean "all server-catalog profiles".
INSERT INTO platform_settings (id, settings)
VALUES (
    1,
    '{
      "defaults": {
        "models": {"llm_profile_id":"legacy-llm","vlm_profile_id":"legacy-vlm"},
        "ingestion": {
          "parser":"docling","chunking_strategy":"recursive","chunk_size":800,
          "enable_image":true,"enable_table":true,"enable_equation":true,"enable_video":false,
          "entity_types":[],"minimum_relation_degree":0
        },
        "retrieval": {
          "preset":"balanced","rrf_k":60,"bm25_top_k":50,"vector_top_k":100,
          "graph_top_k":30,"graph_depth":2,"channels":["bm25","vector","graph"],
          "bm25_tokenizer":"jieba","bm25_k1":1.5,"bm25_b":0.75
        },
        "runtime": {"llm_timeout":180,"personal_concurrency":7}
      },
      "allowed": {
        "llm_profile_ids":[],"vlm_profile_ids":[],"embedding_profile_ids":[],
        "parsers":[],"chunking_strategies":[],"bm25_tokenizers":[]
      },
      "limits": {
        "personal_concurrency":7,"llm_timeout":600,
        "bm25_top_k":1000,"vector_top_k":1000,"graph_top_k":1000,
        "graph_depth":32,"worker_concurrency":64,"provider_concurrency":64,
        "cache_capacity":100000,"interactive_wait_seconds":30
      },
      "state": {"retrieval_preset_version":"v1","read_only":false}
    }'::jsonb
)
ON CONFLICT (id) DO NOTHING;

-- Profile-scoped visual vectors and reindex state used to be provisioned
-- through runtime DDL.  Formalize them in this additive migration so a clean
-- production deployment has all durable state before the application starts.
ALTER TABLE image_vision_vectors
    ADD COLUMN IF NOT EXISTS profile_id TEXT,
    ADD COLUMN IF NOT EXISTS profile_fingerprint TEXT,
    ADD COLUMN IF NOT EXISTS embedding_dim INTEGER,
    ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS vision_vector_migration_issues (
    vector_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO vision_vector_migration_issues(vector_id, reason)
SELECT id, 'missing_workspace'
FROM image_vision_vectors
WHERE workspace = ''
ON CONFLICT(vector_id) DO UPDATE SET reason = EXCLUDED.reason;

DO $$
DECLARE
    embedding_udt TEXT;
BEGIN
    SELECT udt_name INTO embedding_udt
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'image_vision_vectors'
      AND column_name = 'embedding';

    IF embedding_udt = 'vector' THEN
        EXECUTE 'UPDATE image_vision_vectors SET embedding_dim = COALESCE(embedding_dim, vector_dims(embedding))';
    ELSE
        EXECUTE 'UPDATE image_vision_vectors SET embedding_dim = COALESCE(embedding_dim, array_length(embedding, 1))';
    END IF;
END $$;

UPDATE image_vision_vectors
SET profile_id = COALESCE(profile_id, 'legacy-doubao-embedding'),
    profile_fingerprint = COALESCE(profile_fingerprint, 'legacy-unscoped');

ALTER TABLE image_vision_vectors
    ALTER COLUMN profile_id SET DEFAULT 'legacy-doubao-embedding',
    ALTER COLUMN profile_id SET NOT NULL,
    ALTER COLUMN profile_fingerprint SET DEFAULT 'legacy-unscoped',
    ALTER COLUMN profile_fingerprint SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ivv_workspace_profile
    ON image_vision_vectors(workspace, profile_id, profile_fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ivv_workspace_profile_hash
    ON image_vision_vectors(workspace, profile_id, profile_fingerprint, generation, image_hash);

CREATE TABLE IF NOT EXISTS vision_reindex_jobs (
    id TEXT PRIMARY KEY,
    kb TEXT NOT NULL,
    actor_id BIGINT NULL,
    source_profile_id TEXT NOT NULL,
    source_fingerprint TEXT,
    source_embedding_dim INTEGER,
    target_profile_id TEXT NOT NULL,
    target_fingerprint TEXT,
    target_embedding_dim INTEGER,
    generation BIGINT NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN ('queued','running','succeeded','failed','cancelled')),
    completed INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    error_code TEXT NULL,
    lease_owner TEXT NULL,
    heartbeat_at TIMESTAMPTZ NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vision_reindex_active_kb
    ON vision_reindex_jobs(kb) WHERE state IN ('queued','running');

-- Old visual partitions are derived data, but NanoVectorDB files cannot be
-- removed transactionally with PostgreSQL activation.  Persist cleanup work
-- so crashes and filesystem failures are retried with an ownership fence.
CREATE TABLE IF NOT EXISTS vision_index_gc_jobs (
    id UUID PRIMARY KEY,
    reindex_job_id TEXT NOT NULL UNIQUE REFERENCES vision_reindex_jobs(id),
    kb TEXT NOT NULL,
    workspace TEXT NOT NULL,
    obsolete_profile_id TEXT NOT NULL,
    obsolete_fingerprint TEXT,
    required_active_profile_id TEXT NOT NULL,
    required_active_fingerprint TEXT,
    generation BIGINT NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN ('queued','running','succeeded','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error_code TEXT NULL,
    lease_owner TEXT NULL,
    heartbeat_at TIMESTAMPTZ NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vision_index_gc_runnable
    ON vision_index_gc_jobs(state, heartbeat_at)
    WHERE state IN ('queued','running');

CREATE TABLE IF NOT EXISTS kb_mutation_leases (
    id UUID PRIMARY KEY,
    kb TEXT NOT NULL,
    task_id VARCHAR(64) NOT NULL,
    lease_owner VARCHAR(128) NOT NULL,
    mutation_kind VARCHAR(32) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (kb, task_id)
);
CREATE INDEX IF NOT EXISTS idx_kb_mutation_leases_active
    ON kb_mutation_leases(kb, expires_at);

CREATE TABLE IF NOT EXISTS kb_corpus_mutations (
    id VARCHAR(128) PRIMARY KEY,
    kb TEXT NOT NULL,
    mutation_kind VARCHAR(32) NOT NULL,
    state VARCHAR(16) NOT NULL CHECK (state IN ('pending','committed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    committed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_kb_corpus_mutations_pending
    ON kb_corpus_mutations(state, created_at) WHERE state = 'pending';

ALTER TABLE kb_metadata
    ADD COLUMN IF NOT EXISTS corpus_revision BIGINT NOT NULL DEFAULT 0;

ALTER TABLE uploaded_files
    ADD COLUMN IF NOT EXISTS processing_owner VARCHAR(128),
    ADD COLUMN IF NOT EXISTS processing_generation BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS processing_heartbeat_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_uploaded_files_processing_heartbeat
    ON uploaded_files(status, processing_heartbeat_at)
    WHERE status = 'processing';

COMMIT;
