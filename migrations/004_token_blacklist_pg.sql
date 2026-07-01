-- ══════════════════════════════════════════════════════════════════════════════
-- RAG-Anything Token 黑名单 + 审计日志 — 建表迁移
-- 迁移编号: 004_token_blacklist_pg
-- 目标数据库: PostgreSQL
--
-- 【本迁移操作的表】
--   token_revocations  已撤销的 JWT Token 记录
--                      family_id — Refresh Token 家族标识，支持整链撤销
--                      当用户登出或修改密码时，同 family 的所有 Token 一并失效
--   audit_logs         审计日志（001 迁移已创建，本迁移确保 PG 路径就绪）
--                      记录敏感操作：创建/删除 KB、修改权限、删除文档等
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- =============================================================================
-- 1. token_revocations: Add family_id for refresh token family tracking
-- =============================================================================
-- Previously, refresh_family tracking was memory-only (token_blacklist.py
-- _refresh_family dict). This column enables cross-worker family revocation.
--
-- family_id is NULL for access tokens (only refresh tokens belong to families).
-- When a refresh token is revoked, all tokens sharing the same family_id
-- are cascade-revoked to prevent replay attacks.

ALTER TABLE token_revocations
ADD COLUMN IF NOT EXISTS family_id TEXT;

-- Index for family-level revocation queries
CREATE INDEX IF NOT EXISTS idx_token_revocations_family
ON token_revocations(family_id) WHERE family_id IS NOT NULL;

-- =============================================================================
-- 2. Add token revocation metadata column (optional, for audit/debug)
-- =============================================================================
ALTER TABLE token_revocations
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- =============================================================================
-- 3. Verification
-- =============================================================================
-- \d+ token_revocations  — verify family_id and metadata columns exist
-- SELECT column_name, data_type FROM information_schema.columns
--   WHERE table_name = 'token_revocations';

COMMIT;
