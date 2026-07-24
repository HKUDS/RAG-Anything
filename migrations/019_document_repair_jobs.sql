BEGIN;

ALTER TABLE processing_tasks
    ADD COLUMN IF NOT EXISTS outcome VARCHAR(32) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS warning_message TEXT NOT NULL DEFAULT '';

ALTER TABLE uploaded_files
    ADD COLUMN IF NOT EXISTS outcome VARCHAR(32) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS warning_message TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS document_repair_jobs (
    id              BIGSERIAL PRIMARY KEY,
    kb_name         VARCHAR(255) NOT NULL,
    doc_id          VARCHAR(255) NOT NULL,
    stage           VARCHAR(64) NOT NULL DEFAULT 'entity_extraction',
    status          VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_until     TIMESTAMPTZ,
    last_error      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (kb_name, doc_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_document_repair_jobs_due
    ON document_repair_jobs (status, next_attempt_at, updated_at);

COMMENT ON TABLE document_repair_jobs IS
    'Durable document enrichment repair queue; text content remains queryable while graph extraction is retried.';

COMMIT;
