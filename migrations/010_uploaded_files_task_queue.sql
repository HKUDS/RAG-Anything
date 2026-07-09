BEGIN;

ALTER TABLE uploaded_files
    ADD COLUMN IF NOT EXISTS error_message TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_uploaded_files_task_id
    ON uploaded_files(task_id)
    WHERE task_id IS NOT NULL;

COMMENT ON COLUMN uploaded_files.status IS
    'queued | processing | completed | failed | deleted';

COMMIT;
