BEGIN;

ALTER TABLE document_tag_jobs
    ADD COLUMN IF NOT EXISTS upload_task_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_document_tag_jobs_upload_task
    ON document_tag_jobs (upload_task_id)
    WHERE upload_task_id <> '';

COMMIT;
