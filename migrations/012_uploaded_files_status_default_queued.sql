BEGIN;

ALTER TABLE uploaded_files
    ALTER COLUMN status SET DEFAULT 'queued';

COMMIT;
