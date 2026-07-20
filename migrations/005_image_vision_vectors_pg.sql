-- ══════════════════════════════════════════════════════════════════════════════
-- RAG-Anything 图片视觉向量存储 — 建表迁移
-- 迁移编号: 005_image_vision_vectors_pg
-- 目标数据库: PostgreSQL
-- 说明: 使用原生 double precision[] 数组存储图片视觉嵌入向量（不需要 pgvector 扩展）
--       同时创建余弦相似度 PL/pgSQL 函数，支持"以图搜图"功能
--
-- 【本迁移创建的表和函数】
--   image_vision_vectors            图片视觉向量表
--                                   kb_name, file_name, embedding(double[]), metadata(JSON)
--   cosine_similarity(a, b)        余弦相似度计算函数（PL/pgSQL）
--   image_vision_vectors_upsert(...)  向量 upsert 工具函数
--
-- 【说明】当 pgvector 扩展可用时，可迁移为 vector(N) 类型：
--   ALTER TABLE image_vision_vectors ALTER COLUMN embedding TYPE vector(2048)
-- ══════════════════════════════════════════════════════════════════════════════
--     USING embedding::vector;
--   CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops);
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. Image Vision Vectors table
-- =============================================================================
-- Replaces: {working_dir}/vdb_image_vision.json (NanoVectorDB file)
--
-- double precision[] is a native PostgreSQL array type. Cosine similarity
-- is computed by the plpgsql function below. Performance is acceptable for
-- up to ~100K vectors (typical KB usage); add pgvector for million-scale.

CREATE TABLE IF NOT EXISTS image_vision_vectors (
    -- Primary key: "img-{sha256_first_16}" (matching legacy NanoVectorDB format)
    id              TEXT PRIMARY KEY,

    -- Knowledge-base workspace. Content-derived document and image IDs are
    -- not globally unique, so every read/write/delete must be KB-scoped.
    workspace       TEXT NOT NULL DEFAULT '',

    -- SHA-256 content hash (first 16 hex chars), indexed for dedup
    image_hash      TEXT NOT NULL,

    -- Associated document ID (for cascade delete by document)
    doc_id          TEXT NOT NULL,

    -- Entity name (from vision model extraction, for display)
    entity_name     TEXT NOT NULL DEFAULT '',

    -- Entity type (e.g. "image"), for future multi-modal filtering
    entity_type     TEXT NOT NULL DEFAULT 'image',

    -- Original image path within the document
    image_path      TEXT NOT NULL DEFAULT '',

    -- File path on disk for re-embedding
    file_path       TEXT NOT NULL DEFAULT '',

    -- Vision model description (max 500 chars, truncated on insert)
    description     TEXT NOT NULL DEFAULT '',

    -- Vision embedding model name (e.g. "doubao-embedding-vision")
    vision_model    TEXT NOT NULL DEFAULT '',

    -- Embedding vector: native double precision array (e.g. ARRAY[0.1, 0.2, ...])
    -- Dimension: 2048 for Doubao Vision, variable for other models
    embedding       double precision[] NOT NULL,

    -- Timestamp (epoch seconds, matching legacy format)
    created_at      DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

-- Index for cascade delete by document
CREATE INDEX IF NOT EXISTS idx_ivv_doc_id
    ON image_vision_vectors(doc_id);

CREATE INDEX IF NOT EXISTS idx_ivv_workspace_doc_id
    ON image_vision_vectors(workspace, doc_id);

-- Index for hash lookup (dedup check)
CREATE INDEX IF NOT EXISTS idx_ivv_image_hash
    ON image_vision_vectors(image_hash);


-- =============================================================================
-- 2. Cosine Similarity Function (PL/pgSQL, native arrays)
-- =============================================================================
-- Computes cosine similarity between two double precision[] vectors.
-- Returns 0.0 on dimension mismatch or null input.
--
-- Formula: dot(a,b) / (||a|| * ||b||)
-- Range: [-1, 1] (1 = identical, 0 = orthogonal, -1 = opposite)

CREATE OR REPLACE FUNCTION array_cosine_similarity(
    a double precision[],
    b double precision[]
) RETURNS double precision
LANGUAGE plpgsql
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
DECLARE
    dot_product double precision := 0;
    norm_a double precision := 0;
    norm_b double precision := 0;
    i integer;
    dim integer;
BEGIN
    -- Dimension must match
    dim := array_length(a, 1);
    IF dim IS NULL OR dim != array_length(b, 1) THEN
        RETURN 0.0;
    END IF;

    -- Compute dot product and norms
    FOR i IN 1..dim LOOP
        dot_product := dot_product + (a[i] * b[i]);
        norm_a := norm_a + (a[i] * a[i]);
        norm_b := norm_b + (b[i] * b[i]);
    END LOOP;

    -- Guard against zero vectors
    IF norm_a = 0.0 OR norm_b = 0.0 THEN
        RETURN 0.0;
    END IF;

    RETURN dot_product / (sqrt(norm_a) * sqrt(norm_b));
END;
$$;


-- =============================================================================
-- 3. Vector Search Helper Function
-- =============================================================================
-- Finds top_k most similar vectors using cosine similarity.
-- Usage:
--   SELECT * FROM search_similar_images(
--       ARRAY[0.1, 0.2, ...]::double precision[],  -- query vector
--       10                                           -- top_k
--   );

CREATE OR REPLACE FUNCTION search_similar_images(
    query_vec double precision[],
    top_k integer DEFAULT 10
) RETURNS TABLE(
    id text,
    image_hash text,
    doc_id text,
    entity_name text,
    entity_type text,
    image_path text,
    file_path text,
    description text,
    vision_model text,
    created_at double precision,
    score double precision
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    RETURN QUERY
    SELECT
        v.id,
        v.image_hash,
        v.doc_id,
        v.entity_name,
        v.entity_type,
        v.image_path,
        v.file_path,
        v.description,
        v.vision_model,
        v.created_at,
        array_cosine_similarity(v.embedding, query_vec) AS score
    FROM image_vision_vectors v
    ORDER BY score DESC
    LIMIT top_k;
END;
$$;


-- =============================================================================
-- 4. Verification
-- =============================================================================
-- \d+ image_vision_vectors  — verify table structure
-- \df array_cosine_similarity — verify cosine function exists
-- \df search_similar_images — verify search function exists

COMMIT;
