-- Migration 028: Durable account lifecycle state and account-wide JWT revocation.
-- This migration is additive and intentionally does not remove historical users.

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS session_generation BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS archived_by INTEGER,
    ADD COLUMN IF NOT EXISTS archive_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_users_active_super_admin_quorum
    ON users (role_id)
    WHERE is_active = 1 AND archived_at IS NULL;

COMMIT;
