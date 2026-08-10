-- ============================================================================
-- Migration: 010_manufacturing_to_autorepair_permissions.sql
-- Description: Rename manufacturing:* permissions to autorepair:*
--              for auto-repair domain rebranding.
-- Date: 2026-07-03
-- ============================================================================

-- Verify current state before migration
-- SELECT name, permissions FROM roles
-- WHERE permissions ?| array['manufacturing:read', 'manufacturing:write'];

BEGIN;

-- Replace manufacturing permissions while preserving JSON array order.
UPDATE roles
SET permissions = (
    SELECT COALESCE(
        jsonb_agg(
            to_jsonb(
                CASE value
                    WHEN 'manufacturing:read' THEN 'autorepair:read'
                    WHEN 'manufacturing:write' THEN 'autorepair:write'
                    ELSE value
                END
            ) ORDER BY ordinal
        ),
        '[]'::jsonb
    )
    FROM jsonb_array_elements_text(permissions)
         WITH ORDINALITY AS items(value, ordinal)
)
WHERE permissions ?| array['manufacturing:read', 'manufacturing:write'];

-- Update KB domain from manufacturing → autorepair.
UPDATE kb_metadata SET domain = 'autorepair' WHERE domain = 'manufacturing';

-- Update the extensible metadata JSON (backward-compatible field).
UPDATE kb_metadata
SET extra = jsonb_set(extra, '{domain}', '"autorepair"', true)
WHERE extra->>'domain' = 'manufacturing';

COMMIT;

-- Verify after migration
-- SELECT name, permissions FROM roles
-- WHERE permissions ?| array['autorepair:read', 'autorepair:write'];
-- SELECT name, domain FROM kb_metadata WHERE domain = 'autorepair';
