-- Persist the new object-level KB member-management capability for roles that
-- may manage members.  Runtime role seeding carries the same definition.
UPDATE roles
SET permissions = CASE
    WHEN permissions ? 'kb:manage' THEN permissions
    ELSE permissions || '["kb:manage"]'::jsonb
END
WHERE name IN ('super_admin', 'dept_admin', 'teacher');
