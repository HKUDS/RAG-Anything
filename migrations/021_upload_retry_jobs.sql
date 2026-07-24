BEGIN;

ALTER TABLE processing_tasks
    ADD COLUMN IF NOT EXISTS retryable BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS failure_stage VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS upload_retry_jobs (
    id BIGSERIAL PRIMARY KEY,
    upload_id BIGINT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
    task_id VARCHAR(64) NOT NULL,
    kb_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    filename VARCHAR(500) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    user_id INTEGER NOT NULL DEFAULT 0,
    stage VARCHAR(64) NOT NULL DEFAULT 'model_preflight',
    chunking_strategy VARCHAR(50) NOT NULL DEFAULT '',
    enable_image BOOLEAN,
    enable_table BOOLEAN,
    enable_equation BOOLEAN,
    enable_video BOOLEAN,
    status VARCHAR(24) NOT NULL DEFAULT 'retry_wait'
        CHECK (status IN ('queued','running','retry_wait','completed','terminal_failed','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 1,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    root_type VARCHAR(255) NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_upload_retry_job_stage UNIQUE (upload_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_upload_retry_due
    ON upload_retry_jobs(next_attempt_at, id)
    WHERE status IN ('queued', 'retry_wait', 'running');
CREATE INDEX IF NOT EXISTS idx_upload_retry_task
    ON upload_retry_jobs(task_id, updated_at DESC);

COMMIT;
