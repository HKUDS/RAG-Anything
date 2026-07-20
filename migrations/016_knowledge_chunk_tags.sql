-- Knowledge-base scoped tags for document chunks.
-- These tables deliberately do not reference LightRAG tables: chunk ids are
-- content hashes and can change when a user edits a chunk.

CREATE TABLE IF NOT EXISTS kb_tags (
    id              BIGSERIAL PRIMARY KEY,
    kb_name         TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    created_by      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_kb_tags_normalized_name UNIQUE (kb_name, normalized_name)
);

CREATE INDEX IF NOT EXISTS idx_kb_tags_lookup
    ON kb_tags (kb_name, normalized_name);

CREATE TABLE IF NOT EXISTS chunk_tag_assignments (
    tag_id       BIGINT NOT NULL REFERENCES kb_tags(id) ON DELETE CASCADE,
    kb_name      TEXT NOT NULL,
    document_id  TEXT NOT NULL,
    chunk_id     TEXT NOT NULL,
    created_by   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tag_id, kb_name, document_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_chunk_tag_assignments_chunk
    ON chunk_tag_assignments (kb_name, document_id, chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunk_tag_assignments_tag
    ON chunk_tag_assignments (kb_name, tag_id, document_id, chunk_id);
