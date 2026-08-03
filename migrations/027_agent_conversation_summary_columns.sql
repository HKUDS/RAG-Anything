-- Migration 027: Repair conversation summary columns for existing deployments.
-- This is intentionally idempotent because migration 009 was not included in
-- the historical PostgreSQL setup entrypoint.

BEGIN;

ALTER TABLE agent_conversations
ADD COLUMN IF NOT EXISTS summary TEXT;

ALTER TABLE agent_conversations
ADD COLUMN IF NOT EXISTS summary_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_agent_conversations_summary
ON agent_conversations (summary_updated_at)
WHERE summary IS NOT NULL;

COMMIT;
