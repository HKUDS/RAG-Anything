-- Restore the canonical five-level RBAC model.
-- Safe to run repeatedly: canonical role definitions are upserted and only
-- accounts still assigned to the temporary three-role model are remapped.

BEGIN;

INSERT INTO roles (name, description, permissions)
VALUES
    ('super_admin', '超级管理员，拥有全部权限（信息中心/IT运维）',
     '["users:read","users:write","users:delete","kb:read","kb:write","kb:delete","agent:read","agent:write","agent:delete","settings:read","settings:write","audit:read","monitor:read","analytics:read","workflow:read","workflow:write","graph:read","graph:write","autorepair:read","autorepair:write"]'::jsonb),
    ('dept_admin', '系部管理员，管理系统内知识库、智能体和用户（系主任/实训中心主任）',
     '["users:read","users:write","kb:read","kb:write","kb:delete","agent:read","agent:write","agent:delete","settings:read","audit:read","monitor:read","analytics:read","workflow:read","workflow:write","graph:read","graph:write","autorepair:read","autorepair:write"]'::jsonb),
    ('teacher', '主讲教师，可创建管理自有知识库和智能体（任课教师）',
     '["kb:read","kb:write","agent:read","agent:write","monitor:read","analytics:read","workflow:read","graph:read","graph:write","autorepair:read","autorepair:write"]'::jsonb),
    ('assistant', '助理教师，可编辑知识库内容、使用智能体（实训指导教师/助教）',
     '["kb:read","kb:write","agent:read","monitor:read","graph:read","graph:write","autorepair:read"]'::jsonb),
    ('student', '学生，可查看知识库并使用智能体问答（各年级学生）',
     '["kb:read","agent:read","graph:read","autorepair:read"]'::jsonb)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    permissions = EXCLUDED.permissions;

UPDATE users AS u
SET role_id = canonical.id,
    updated_at = NOW()
FROM roles AS legacy
JOIN (VALUES
    ('admin', 'super_admin'),
    ('editor', 'teacher'),
    ('viewer', 'student')
) AS mapping(legacy_name, canonical_name) ON mapping.legacy_name = legacy.name
JOIN roles AS canonical ON canonical.name = mapping.canonical_name
WHERE u.role_id = legacy.id;

COMMIT;
