-- =============================================================================
-- RAG-Anything P0 PG Migration: Agents + KB Metadata
-- Migration: 003_p0_agent_kb_meta
-- Target: PostgreSQL (existing raganything-pg container)
-- Description: Replace agent_meta.json, agent_conversations/*.json,
--              and rag_storage_kb_meta.json with proper PG tables.
--
-- Cross-DB note: owner_id / user_id references users(id). No FK possible
--   across databases (users table is in SQLite auth.db when PG auth not used,
--   or in PG when DATABASE_URL is set). Application-layer integrity enforced.
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. kb_metadata — Knowledge Base registry (replaces rag_storage_kb_meta.json)
-- =============================================================================
--
-- Access Patterns:
--   READ (list):  SELECT * FROM kb_metadata ORDER BY created_at DESC
--   READ (single): SELECT * FROM kb_metadata WHERE name = $1
--   WRITE:        INSERT ... ON CONFLICT (name) DO UPDATE (upsert)
--   DELETE:       DELETE FROM kb_metadata WHERE name = $1
--
-- Row Estimates:
--   KBs per deployment: typically 1-20. Max ~100 for heavy multi-tenant use.
--   This is a tiny table — no partitioning needed.

CREATE TABLE IF NOT EXISTS kb_metadata (
    -- KB name (unique identifier, e.g. "default", "manufacturing")
    -- VARCHAR(255) matches typical KB name lengths and the existing
    -- kb_dir() naming convention.
    name            VARCHAR(255) PRIMARY KEY,

    -- Display name (e.g. "默认知识库", "制造知识库")
    display_name    VARCHAR(500) NOT NULL DEFAULT '',

    -- Domain category for filtering (e.g. "general", "manufacturing", "education")
    domain          VARCHAR(100) NOT NULL DEFAULT 'general',

    -- KB description
    description     TEXT NOT NULL DEFAULT '',

    -- Owning user. INTEGER matches users(id).
    -- Cross-database reference — no FK possible.
    owner_id        INTEGER NOT NULL DEFAULT 0,

    -- Denormalized owner username for display efficiency.
    owner_username  VARCHAR(255) NOT NULL DEFAULT '',

    -- Processing status: 'ready', 'processing', 'failed'
    status          VARCHAR(20) NOT NULL DEFAULT 'ready',

    -- Document count (denormalized for fast listing)
    document_count  INTEGER NOT NULL DEFAULT 0,

    -- Extensible metadata blob for future fields without schema changes
    extra           JSONB NOT NULL DEFAULT '{}',

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for listing KBs by owner (most common list query)
CREATE INDEX idx_kb_metadata_owner
    ON kb_metadata(owner_id, updated_at DESC);

-- Index for domain filtering (used by manufacturing KB discovery)
CREATE INDEX idx_kb_metadata_domain
    ON kb_metadata(domain) WHERE domain != 'general';


-- =============================================================================
-- 2. agents — Agent configurations (replaces agent_meta.json)
-- =============================================================================
--
-- Access Patterns:
--   LIST (user):   SELECT * FROM agents WHERE owner_id = $1 OR owner_id = 0
--                  ORDER BY updated_at DESC
--   LIST (admin):  SELECT * FROM agents ORDER BY updated_at DESC
--   READ (single): SELECT * FROM agents WHERE id = $1
--   CREATE:        INSERT INTO agents (...)
--   UPDATE:        UPDATE agents SET ... WHERE id = $1
--   DELETE:        DELETE FROM agents WHERE id = $1
--                  (CASCADE deletes all conversations + messages)
--
-- Row Estimates:
--   Agents: typically 3-20 per deployment (max ~100).
--   This is a tiny table.

CREATE TABLE IF NOT EXISTS agents (
    -- Agent identifier. UUID-style string (8-char hex from the app).
    -- Matches AgentConfig.id format.
    id              VARCHAR(50) PRIMARY KEY,

    -- Display name
    name            VARCHAR(200) NOT NULL DEFAULT '新智能体',

    -- Emoji icon
    icon            VARCHAR(10) NOT NULL DEFAULT '🤖',

    -- Description text
    description     TEXT NOT NULL DEFAULT '',

    -- Welcome message shown on first interaction
    welcome_message TEXT NOT NULL DEFAULT '',

    -- Associated knowledge base name
    kb_name         VARCHAR(255) NOT NULL DEFAULT 'default',

    -- LLM configuration
    llm_model       VARCHAR(100) NOT NULL DEFAULT 'qwen-plus',
    temperature     REAL NOT NULL DEFAULT 0.0,
    max_response_tokens INTEGER NOT NULL DEFAULT 4096,

    -- Query/retrieval configuration
    query_mode      VARCHAR(20) NOT NULL DEFAULT 'hybrid',
    agent_mode      VARCHAR(20) NOT NULL DEFAULT 'none',
    retrieval_top_k INTEGER NOT NULL DEFAULT 40,
    chunk_top_k     INTEGER NOT NULL DEFAULT 20,
    enable_rerank   BOOLEAN NOT NULL DEFAULT FALSE,
    include_references BOOLEAN NOT NULL DEFAULT TRUE,

    -- System prompt
    system_prompt   TEXT NOT NULL DEFAULT '',
    use_default_prompt BOOLEAN NOT NULL DEFAULT TRUE,

    -- Ownership
    owner_id        INTEGER NOT NULL DEFAULT 0,
    owner_username  VARCHAR(255) NOT NULL DEFAULT '',

    -- Template reference (for cloning)
    template_id     VARCHAR(50) NOT NULL DEFAULT '',

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Safety constraint: name length for display
    CONSTRAINT chk_agents_name_length CHECK (char_length(name) <= 200)
);

-- Index for user-isolated listing (most common query)
-- WHERE owner_id = $1 OR owner_id = 0 ORDER BY updated_at DESC
CREATE INDEX idx_agents_owner_updated
    ON agents(owner_id, updated_at DESC);

-- Index for admin "all agents" listing
CREATE INDEX idx_agents_updated
    ON agents(updated_at DESC);


-- =============================================================================
-- 3. agent_conversations — Agent-scoped conversation threads
-- =============================================================================
--
-- Replaces: agent_conversations/<agent_id>/<thread_id>.json
--
-- Key differences from the shared conversations table:
--   - Scoped by agent_id (each agent has its own conversation namespace)
--   - Tracks kb_name and llm_model at thread level (for context switching)
--
-- Relationship:
--   agents 1──N agent_conversations 1──N agent_messages

CREATE TABLE IF NOT EXISTS agent_conversations (
    -- Thread identifier. UUID-style string (8-char hex from the app).
    id              VARCHAR(50) PRIMARY KEY,

    -- Parent agent. CASCADE DELETE: when an agent is deleted, all its
    -- conversations and messages are automatically removed.
    agent_id        VARCHAR(50) NOT NULL
                    REFERENCES agents(id) ON DELETE CASCADE,

    -- Owning user
    owner_id        INTEGER NOT NULL DEFAULT 0,

    -- Display title
    title           VARCHAR(100) NOT NULL DEFAULT '新对话',

    -- KB context at thread creation (may differ from agent default)
    kb_name         VARCHAR(255) NOT NULL DEFAULT '',

    -- LLM model at thread creation
    llm_model       VARCHAR(100) NOT NULL DEFAULT '',

    -- System prompt at thread level (for per-thread customization)
    system_prompt   TEXT NOT NULL DEFAULT '',

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_agent_conv_title_length CHECK (char_length(title) <= 100)
);

-- Index for listing threads by agent, newest first
CREATE INDEX idx_agent_conv_agent_updated
    ON agent_conversations(agent_id, updated_at DESC);

-- Index for listing threads by owner (cross-agent view)
CREATE INDEX idx_agent_conv_owner
    ON agent_conversations(owner_id, updated_at DESC);


-- =============================================================================
-- 4. agent_messages — Messages within agent conversation threads
-- =============================================================================
--
-- Normalized (like shared messages table) rather than JSONB column because:
--   1. Append-only — no partial modifications to message arrays
--   2. Enables future cross-thread message search
--   3. Clean constraint enforcement at DB level

CREATE TABLE IF NOT EXISTS agent_messages (
    -- Synthetic PK
    id          BIGSERIAL PRIMARY KEY,

    -- Parent thread. CASCADE DELETE: remove messages when thread is deleted.
    thread_id   VARCHAR(50) NOT NULL
                REFERENCES agent_conversations(id) ON DELETE CASCADE,

    -- Message role
    role        VARCHAR(10) NOT NULL,

    -- Message content
    content     TEXT NOT NULL,

    -- Additional metadata (e.g. elapsed time, KB name, citations)
    -- Stored as JSONB for flexibility without schema changes
    metadata    JSONB NOT NULL DEFAULT '{}',

    -- Timestamp
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Domain constraints
    CONSTRAINT chk_agent_msg_role CHECK (role IN ('user', 'assistant', 'system')),
    CONSTRAINT chk_agent_msg_content CHECK (char_length(content) <= 10000)
);

-- Index for fetching messages by thread, newest first
CREATE INDEX idx_agent_msg_thread_created
    ON agent_messages(thread_id, created_at DESC);


-- =============================================================================
-- 5. Triggers: auto-update updated_at for kb_metadata, agents, agent_conversations
-- =============================================================================

-- Reuse existing trigger function from 001_shared_state_tables.sql
-- (update_updated_at_column). If that migration hasn't been run, create it.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column'
    ) THEN
        CREATE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $fn$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $fn$ LANGUAGE plpgsql;
    END IF;
END $$;

-- Attach triggers
DROP TRIGGER IF EXISTS trg_kb_metadata_updated_at ON kb_metadata;
CREATE TRIGGER trg_kb_metadata_updated_at
    BEFORE UPDATE ON kb_metadata
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_agents_updated_at ON agents;
CREATE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_agent_conversations_updated_at ON agent_conversations;
CREATE TRIGGER trg_agent_conversations_updated_at
    BEFORE UPDATE ON agent_conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMIT;

-- =============================================================================
-- Verification Queries (run after migration)
-- =============================================================================
-- \dt+                           — list all tables with sizes
-- \di+                           — list all indexes
-- \d+ kb_metadata                — describe kb_metadata table
-- \d+ agents                     — describe agents table
-- \d+ agent_conversations        — describe agent_conversations table
-- \d+ agent_messages             — describe agent_messages table
--
-- Test query patterns:
--   SELECT * FROM kb_metadata ORDER BY updated_at DESC;
--   SELECT * FROM agents WHERE owner_id = 1 OR owner_id = 0 ORDER BY updated_at DESC;
--   SELECT * FROM agent_conversations WHERE agent_id = 'abc123' ORDER BY updated_at DESC;
--   SELECT * FROM agent_messages WHERE thread_id = 'th_abc123' ORDER BY created_at DESC;
-- =============================================================================
