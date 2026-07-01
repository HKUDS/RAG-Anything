-- ══════════════════════════════════════════════════════════════════════════════
-- RAG-Anything RBAC 角色升级: 3→5 角色体系
-- 迁移编号: 002_pg_3to5_roles
-- 前置条件: 已运行 001_pg_schema.sql 创建基础表结构
-- 执行方式: psql -U raganything -d raganything -f migrations/002_pg_3to5_roles.sql
-- 安全特性: 使用事务包裹，失败自动回滚；旧角色不删除（向后兼容）
--
-- 【5 级角色体系】
--   1 = admin  (管理员)    — 全部权限
--   2 = editor (编辑)      — 读写知识库和智能体
--   3 = viewer (只读)      — 只能查看
--   4 = student(学生)      — 受限访问
--   5 = guest  (访客)      — 最小权限
--
-- 【本迁移操作的表】
--   roles    角色定义表（id, name, permissions JSON）
--   users    用户表（username, email, password_hash, role 关联）
-- ══════════════════════════════════════════════════════════════════════════════
-- RAG-Anything PostgreSQL 角色升级: 3→5 角色体系
-- Version: 002
-- Apply:  psql -U raganything -d raganything -f migrations/002_pg_3to5_roles.sql
-- Verify: psql -U raganything -d raganything -c "SELECT id, name FROM roles ORDER BY id"
--
-- 前置条件: 已运行 001_pg_schema.sql 创建基础表结构
-- 安全特性: 使用事务包裹，失败自动回滚；旧角色不删除（向后兼容）

BEGIN;

-- ═══════════════════════════════════════════════════════════════
-- Step 1: 插入 5 个新角色 (ON CONFLICT 跳过已存在的)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO roles (name, description, permissions)
VALUES
    ('super_admin', '超级管理员，拥有全部权限（信息中心/IT运维）',
     '["users:read","users:write","users:delete","kb:read","kb:write","kb:delete","agent:read","agent:write","agent:delete","settings:read","settings:write","audit:read","monitor:read","analytics:read","workflow:read","workflow:write","manufacturing:read","manufacturing:write"]'::jsonb),
    ('dept_admin', '系部管理员，管理系统内知识库、智能体和用户（系主任/实训中心主任）',
     '["users:read","users:write","kb:read","kb:write","kb:delete","agent:read","agent:write","agent:delete","settings:read","audit:read","monitor:read","analytics:read","workflow:read","workflow:write","manufacturing:read","manufacturing:write"]'::jsonb),
    ('teacher', '主讲教师，可创建管理自有知识库和智能体（任课教师）',
     '["kb:read","kb:write","agent:read","agent:write","monitor:read","analytics:read","workflow:read","manufacturing:read","manufacturing:write"]'::jsonb),
    ('assistant', '助理教师，可编辑知识库内容、使用智能体（实训指导教师/助教）',
     '["kb:read","kb:write","agent:read","monitor:read","manufacturing:read"]'::jsonb),
    ('student', '学生，可查看知识库并使用智能体问答（各年级学生）',
     '["kb:read","agent:read","manufacturing:read"]'::jsonb)
ON CONFLICT (name) DO NOTHING;

-- ═══════════════════════════════════════════════════════════════
-- Step 2: 用户角色映射 (旧 → 新)
--   admin  → super_admin
--   editor → teacher
--   viewer → student
-- ═══════════════════════════════════════════════════════════════

-- 2a. admin → super_admin
UPDATE users u
SET role_id = new.id, updated_at = NOW()
FROM roles old, roles new
WHERE u.role_id = old.id
  AND old.name = 'admin'
  AND new.name = 'super_admin';

-- 2b. editor → teacher
UPDATE users u
SET role_id = new.id, updated_at = NOW()
FROM roles old, roles new
WHERE u.role_id = old.id
  AND old.name = 'editor'
  AND new.name = 'teacher';

-- 2c. viewer → student
UPDATE users u
SET role_id = new.id, updated_at = NOW()
FROM roles old, roles new
WHERE u.role_id = old.id
  AND old.name = 'viewer'
  AND new.name = 'student';

-- ═══════════════════════════════════════════════════════════════
-- Step 3: 验证迁移结果
-- ═══════════════════════════════════════════════════════════════

DO $$
DECLARE
    old_role_count INT;
    unmapped_count INT;
BEGIN
    -- 检查是否还有用户指向旧角色
    SELECT COUNT(*) INTO unmapped_count
    FROM users u
    JOIN roles r ON u.role_id = r.id
    WHERE r.name IN ('admin', 'editor', 'viewer');

    IF unmapped_count > 0 THEN
        RAISE WARNING '仍有 % 个用户指向旧角色，请手动检查', unmapped_count;
    END IF;

    -- 检查新角色是否完整
    SELECT COUNT(*) INTO old_role_count
    FROM roles
    WHERE name IN ('super_admin', 'dept_admin', 'teacher', 'assistant', 'student');

    RAISE NOTICE '新角色数量: % (预期 5)', old_role_count;
    RAISE NOTICE '迁移完成: admin→super_admin, editor→teacher, viewer→student';
END;
$$;

COMMIT;

-- ═══════════════════════════════════════════════════════════════
-- 可选: 删除旧角色（仅在确认无用户使用后执行）
-- ═══════════════════════════════════════════════════════════════
-- DELETE FROM roles WHERE name IN ('admin', 'editor', 'viewer');
