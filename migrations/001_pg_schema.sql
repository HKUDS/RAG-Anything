-- RAG-Anything PostgreSQL Schema Migration
-- Version: 001
-- Apply:  psql -U raganything -d raganything -f migrations/001_pg_schema.sql
-- Verify: psql -U raganything -d raganything -c "\dt"

-- ═══════════════════════════════════════════════════════════════
-- Auth: Roles → Users → Settings → Audit Logs → Token Revocations
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS roles (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    permissions JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id                     SERIAL PRIMARY KEY,
    username               TEXT UNIQUE NOT NULL,
    email                  TEXT UNIQUE NOT NULL,
    password_hash          TEXT NOT NULL,
    role_id                INTEGER REFERENCES roles(id) DEFAULT NULL,
    is_admin               INTEGER DEFAULT 0,
    is_active              INTEGER DEFAULT 1,
    failed_login_attempts  INTEGER DEFAULT 0,
    locked_until           TIMESTAMPTZ DEFAULT NULL,
    last_login_at          TIMESTAMPTZ DEFAULT NULL,
    must_change_password   INTEGER DEFAULT 0,
    created_at             TIMESTAMPTZ DEFAULT NOW(),
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id              SERIAL PRIMARY KEY,
    actor_id        INTEGER NOT NULL,
    action          TEXT NOT NULL,
    target_user_id  INTEGER,
    details         JSONB DEFAULT '{}',
    ip_address      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);

CREATE TABLE IF NOT EXISTS token_revocations (
    jti         TEXT PRIMARY KEY,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_token_revocations_expires ON token_revocations(expires_at);

-- ═══════════════════════════════════════════════════════════════
-- State: Query History + Conversations + Messages
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS query_history (
    id              TEXT PRIMARY KEY,
    query           TEXT NOT NULL DEFAULT '',
    mode            TEXT NOT NULL DEFAULT 'text',
    agent_mode      TEXT NOT NULL DEFAULT 'none',
    answer          TEXT NOT NULL DEFAULT '',
    reasoning_trace JSONB DEFAULT '{}',
    images          JSONB DEFAULT '[]',
    time            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    elapsed         DOUBLE PRECISION DEFAULT 0.0,
    kb              TEXT NOT NULL DEFAULT '',
    agent_id        TEXT NOT NULL DEFAULT '',
    thread_id       TEXT NOT NULL DEFAULT '',
    user_id         INTEGER NOT NULL DEFAULT 0,
    username        TEXT NOT NULL DEFAULT '',
    fallback        BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_query_history_user_time ON query_history(user_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_query_history_time ON query_history(time DESC);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    title      TEXT NOT NULL DEFAULT '新对话',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id         SERIAL PRIMARY KEY,
    thread_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content    TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, created_at);

-- Auto-update conversations.updated_at on message insert
CREATE OR REPLACE FUNCTION trg_conversations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations SET updated_at = NOW() WHERE id = NEW.thread_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_conversations_updated_at') THEN
        CREATE TRIGGER trg_conversations_updated_at
        AFTER INSERT ON messages
        FOR EACH ROW EXECUTE FUNCTION trg_conversations_updated_at();
    END IF;
END;
$$;

-- ── Default Roles (五级权限体系) ──────────────────────────

INSERT INTO roles (name, description, permissions)
VALUES
    ('super_admin', '超级管理员，拥有全部权限（信息中心/IT运维）',
     '["users:read","users:write","users:delete","kb:read","kb:write","kb:delete","agent:read","agent:write","agent:delete","settings:read","settings:write","audit:read","monitor:read","analytics:read","workflow:read","workflow:write","manufacturing:read","manufacturing:write"]'),
    ('dept_admin', '系部管理员，管理系统内知识库、智能体和用户（系主任/实训中心主任）',
     '["users:read","users:write","kb:read","kb:write","kb:delete","agent:read","agent:write","agent:delete","settings:read","audit:read","monitor:read","analytics:read","workflow:read","workflow:write","manufacturing:read","manufacturing:write"]'),
    ('teacher', '主讲教师，可创建管理自有知识库和智能体（任课教师）',
     '["kb:read","kb:write","agent:read","agent:write","monitor:read","analytics:read","workflow:read","manufacturing:read","manufacturing:write"]'),
    ('assistant', '助理教师，可编辑知识库内容、使用智能体（实训指导教师/助教）',
     '["kb:read","kb:write","agent:read","monitor:read","manufacturing:read"]'),
    ('student', '学生，可查看知识库并使用智能体问答（各年级学生）',
     '["kb:read","agent:read","manufacturing:read"]')
ON CONFLICT (name) DO NOTHING;
