-- Speed up per-agent activity aggregation for the agent list sort controls.
CREATE INDEX IF NOT EXISTS idx_agent_conversations_agent_owner_updated
ON agent_conversations (agent_id, owner_id, updated_at DESC);
