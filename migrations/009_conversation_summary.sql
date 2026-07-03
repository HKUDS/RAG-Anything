-- Migration 009: Conversation Summary
-- Purpose: Add summary column to agent_conversations for long-conversation compression
-- Date: 2026-07-02
-- Dependency: migrations/003_p0_agent_kb_meta.sql

-- Add summary field for compressed conversation text
ALTER TABLE agent_conversations
ADD COLUMN IF NOT EXISTS summary TEXT;

-- Add timestamp tracking for incremental summary updates
ALTER TABLE agent_conversations
ADD COLUMN IF NOT EXISTS summary_updated_at TIMESTAMPTZ;

-- Index for quickly finding threads that need summary updates
-- (summary_updated_at IS NULL OR updated_at > summary_updated_at)
CREATE INDEX IF NOT EXISTS idx_agent_conversations_summary
ON agent_conversations (summary_updated_at)
WHERE summary IS NOT NULL;
