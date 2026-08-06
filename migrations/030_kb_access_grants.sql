-- Explicit user scope for cross-owner knowledge-base collaboration.
CREATE TABLE IF NOT EXISTS kb_access_grants (
    kb_name TEXT NOT NULL REFERENCES kb_metadata(name) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    granted_by INTEGER NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (kb_name, user_id)
);

CREATE INDEX IF NOT EXISTS idx_kb_access_grants_user
    ON kb_access_grants (user_id, kb_name);
