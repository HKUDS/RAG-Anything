-- ══════════════════════════════════════════════════════════════════════════════
-- RAG-Anything 上传文件元数据 — 建表迁移
-- 迁移编号: 009_uploaded_files_meta
-- 目标数据库: PostgreSQL
-- 说明: 文件本身留在磁盘，此表只存元数据（文件名/路径/哈希/大小/状态/上传者）
--       支持上传历史查询、文件级去重（同 hash + 同 KB 自动去重）、审计追溯
--
-- 【本迁移创建的表】
--   uploaded_files      上传文件元数据
--                       filename  — 原始文件名
--                       file_path — 磁盘绝对路径
--                       file_hash — SHA-256 内容哈希
--                       file_size — 文件大小（字节）
--                       kb_name   — 所属知识库
--                       uploaded_by — 上传者 user_id
--                       task_id   — 关联的处理任务
--                       status    — uploaded / processing / completed / failed / deleted
--                       UNIQUE(file_hash, kb_name) — 同内容同 KB 去重
--
-- 【替换了什么】
--   内存中的 _processing_files dict（进程重启后丢失的去重信息）
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- =============================================================================
-- 1. uploaded_files — file metadata (files stay on disk)
-- =============================================================================
-- Access Patterns:
--   INSERT:       Register file on upload
--   UPDATE:       Set task_id / status after queue or on completion
--   SELECT:       List by kb_name, uploaded_by, or file_hash (dedup)
--   DELETE:       (rare) cleanup when file deleted from disk

CREATE TABLE IF NOT EXISTS uploaded_files (
    id           BIGSERIAL PRIMARY KEY,
    filename     VARCHAR(500) NOT NULL,
    file_path    VARCHAR(1000) NOT NULL,
    file_hash    VARCHAR(64) NOT NULL,
    file_size    BIGINT NOT NULL DEFAULT 0,
    kb_name      VARCHAR(255) NOT NULL,
    uploaded_by  INTEGER NOT NULL,
    task_id      VARCHAR(50),
    status       VARCHAR(20) NOT NULL DEFAULT 'uploaded',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Dedup: same content hash + same KB = duplicate
    CONSTRAINT uq_uploaded_files_hash_kb UNIQUE (file_hash, kb_name)
);

-- Status values for documentation / check constraint
COMMENT ON COLUMN uploaded_files.status IS
    'uploaded | processing | completed | failed | deleted';

COMMENT ON TABLE uploaded_files IS
    'Uploaded file metadata (files stored on filesystem, not in PG)';

-- Index: list files in a KB, most recent first
CREATE INDEX IF NOT EXISTS idx_uploaded_files_kb_time
    ON uploaded_files(kb_name, created_at DESC);

-- Index: user upload history
CREATE INDEX IF NOT EXISTS idx_uploaded_files_user_time
    ON uploaded_files(uploaded_by, created_at DESC);

-- Index: dedup lookup by hash + kb (backed by UNIQUE constraint)
-- CREATE UNIQUE INDEX IF NOT EXISTS idx_uploaded_files_hash_kb
--     ON uploaded_files(file_hash, kb_name);  -- already enforced by uq_uploaded_files_hash_kb

-- Trigger: auto-update updated_at
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_uploaded_files_updated_at'
    ) THEN
        CREATE TRIGGER trg_uploaded_files_updated_at
            BEFORE UPDATE ON uploaded_files
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- =============================================================================
-- Verification
-- =============================================================================
-- SELECT * FROM uploaded_files ORDER BY created_at DESC;
-- SELECT count(*) FROM uploaded_files WHERE kb_name = 'default';
-- SELECT count(*) FROM uploaded_files WHERE uploaded_by = 1;

COMMIT;
