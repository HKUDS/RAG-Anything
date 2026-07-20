-- Scope PostgreSQL vision vectors to a knowledge-base workspace.
--
-- Existing rows remain in the legacy empty workspace. New application code
-- intentionally does not read them because their original KB cannot be
-- reconstructed safely from content-derived IDs.

BEGIN;

ALTER TABLE image_vision_vectors
    ADD COLUMN IF NOT EXISTS workspace TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_ivv_workspace_doc_id
    ON image_vision_vectors(workspace, doc_id);

COMMIT;
