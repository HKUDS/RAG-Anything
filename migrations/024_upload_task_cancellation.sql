BEGIN;

COMMENT ON COLUMN uploaded_files.status IS
    'queued | processing | retry_wait | cancelling | completed | failed | deleted';

COMMIT;
