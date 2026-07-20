-- Preserve manual tags while allowing generated document and chunk keywords.

ALTER TABLE chunk_tag_assignments
    ADD COLUMN IF NOT EXISTS assignment_kind TEXT NOT NULL DEFAULT 'manual';

DO $$
BEGIN
    ALTER TABLE chunk_tag_assignments
        ADD CONSTRAINT chk_chunk_tag_assignment_kind
        CHECK (assignment_kind IN ('manual', 'auto_document', 'auto_chunk'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_chunk_tag_assignments_kind
    ON chunk_tag_assignments (kb_name, document_id, assignment_kind, chunk_id);
