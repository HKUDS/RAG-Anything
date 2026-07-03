-- ============================================================================
-- Migration: 010_manufacturing_to_autorepair_permissions.sql
-- Description: Rename manufacturing:* permissions to autorepair:*
--              for auto-repair domain rebranding.
-- Date: 2026-07-03
-- ============================================================================

-- Verify current state before migration
-- SELECT role_name, permissions FROM roles
-- WHERE 'manufacturing:read' = ANY(permissions)
--    OR 'manufacturing:write' = ANY(permissions);

BEGIN;

-- Replace manufacturing:read → autorepair:read
UPDATE roles
SET permissions = array_replace(permissions, 'manufacturing:read', 'autorepair:read')
WHERE 'manufacturing:read' = ANY(permissions);

-- Replace manufacturing:write → autorepair:write
UPDATE roles
SET permissions = array_replace(permissions, 'manufacturing:write', 'autorepair:write')
WHERE 'manufacturing:write' = ANY(permissions);

-- Update KB domain from manufacturing → autorepair
-- (Existing KBs in pg_kb_meta use domain='manufacturing')
UPDATE pg_kb_meta SET domain = 'autorepair' WHERE domain = 'manufacturing';

-- Update KB metadata JSON (backward compat field)
UPDATE pg_kb_meta
SET meta = jsonb_set(meta, '{domain}', '"autorepair"')
WHERE meta->>'domain' = 'manufacturing';

COMMIT;

-- Verify after migration
-- SELECT role_name, permissions FROM roles
-- WHERE 'autorepair:read' = ANY(permissions)
--    OR 'autorepair:write' = ANY(permissions);
-- SELECT kb_name, domain FROM pg_kb_meta WHERE domain = 'autorepair';
