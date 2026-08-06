-- 032: Bind each KB workspace to one text embedding identity.
CREATE TABLE IF NOT EXISTS kb_text_embedding_identities (
    workspace TEXT PRIMARY KEY,
    identity_hash TEXT NOT NULL,
    identity JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_text_embedding_identity_hash
    ON kb_text_embedding_identities (identity_hash);
