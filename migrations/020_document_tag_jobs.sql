BEGIN;

CREATE TABLE IF NOT EXISTS document_tag_jobs (
    id              BIGSERIAL PRIMARY KEY,
    kb_name         TEXT NOT NULL,
    doc_id          TEXT NOT NULL,
    filename        TEXT NOT NULL DEFAULT '',
    user_id         INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_until     TIMESTAMPTZ,
    lease_token     TEXT NOT NULL DEFAULT '',
    priority        INTEGER NOT NULL DEFAULT 100,
    last_error      TEXT NOT NULL DEFAULT '',
    assigned_count  INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    eligible_chunk_count INTEGER NOT NULL DEFAULT 0,
    tagged_chunk_count INTEGER NOT NULL DEFAULT 0,
    not_applicable_count INTEGER NOT NULL DEFAULT 0,
    content_fingerprint TEXT NOT NULL DEFAULT '',
    rerun_requested BOOLEAN NOT NULL DEFAULT FALSE,
    tagger_version  TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (kb_name, doc_id)
);

CREATE INDEX IF NOT EXISTS idx_document_tag_jobs_priority_due
    ON document_tag_jobs (status, priority DESC, next_attempt_at, updated_at);

COMMIT;
