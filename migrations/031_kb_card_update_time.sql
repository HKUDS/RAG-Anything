-- 031: Repair knowledge-base card update timestamps.
--
-- Migration 026 removed the automatic metadata timestamp trigger, but existing
-- databases can retain it until upgraded and prior full-snapshot saves may have
-- already assigned one timestamp to multiple unrelated KBs. This migration is
-- intentionally conservative: only duplicate timestamp groups are recovered.
-- The inferred value is a best effort from durable terminal uploads and
-- committed corpus mutations; metadata-only historical changes cannot be
-- reconstructed and fall back to the KB creation time.

DROP TRIGGER IF EXISTS trg_kb_metadata_updated_at ON kb_metadata;

WITH duplicate_timestamps AS (
    SELECT updated_at
    FROM kb_metadata
    GROUP BY updated_at
    HAVING COUNT(*) > 1
),
latest_upload AS (
    SELECT kb_name, MAX(updated_at) AS updated_at
    FROM uploaded_files
    WHERE status IN ('completed', 'deleted')
    GROUP BY kb_name
),
latest_mutation AS (
    SELECT kb, MAX(committed_at) AS updated_at
    FROM kb_corpus_mutations
    WHERE state = 'committed'
    GROUP BY kb
),
recovery AS (
    SELECT meta.name,
           GREATEST(
               meta.created_at,
               COALESCE(upload.updated_at, meta.created_at),
               COALESCE(mutation.updated_at, meta.created_at)
           ) AS inferred_updated_at
    FROM kb_metadata AS meta
    INNER JOIN duplicate_timestamps AS duplicate
        ON duplicate.updated_at = meta.updated_at
    LEFT JOIN latest_upload AS upload ON upload.kb_name = meta.name
    LEFT JOIN latest_mutation AS mutation ON mutation.kb = meta.name
)
UPDATE kb_metadata AS meta
SET updated_at = recovery.inferred_updated_at
FROM recovery
WHERE meta.name = recovery.name
  AND meta.updated_at > recovery.inferred_updated_at;
