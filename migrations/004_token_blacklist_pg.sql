-- =============================================================================
-- RAG-Anything Phase 1 PG Migration: Token Blacklist + Audit Log PG Path
-- Migration: 004_token_blacklist_pg
-- Target: PostgreSQL (existing raganything-pg container)
-- Description:
--   1. Add family_id column to token_revocations for refresh family tracking
--   2. Ensure audit_logs table is ready for PG writes (already created by 001)
-- =============================================================================

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
