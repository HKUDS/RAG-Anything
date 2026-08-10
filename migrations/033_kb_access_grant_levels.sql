-- Give each durable cross-owner KB grant an explicit scope level.
ALTER TABLE kb_access_grants
    ADD COLUMN IF NOT EXISTS access_level TEXT NOT NULL DEFAULT 'read';

-- Preserve the previous effective write behavior for roles that already own
-- kb:write.  All other existing grants become read-only.
UPDATE kb_access_grants AS grant_row
SET access_level = CASE
    WHEN EXISTS (
        SELECT 1
        FROM users
        JOIN roles ON roles.id = users.role_id
        WHERE users.id = grant_row.user_id
          AND roles.permissions ? 'kb:write'
    ) THEN 'operate'
    ELSE 'read'
END;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'kb_access_grants_access_level_check'
          AND conrelid = 'kb_access_grants'::regclass
    ) THEN
        ALTER TABLE kb_access_grants
            ADD CONSTRAINT kb_access_grants_access_level_check
            CHECK (access_level IN ('read', 'operate'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_kb_access_grants_kb_level
    ON kb_access_grants (kb_name, access_level, user_id);
