-- Durable parent assets and time-bounded video segments.
CREATE TABLE IF NOT EXISTS video_assets (
    media_id TEXT PRIMARY KEY,
    kb_name TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    server_path TEXT NOT NULL,
    duration_ms BIGINT NOT NULL CHECK (duration_ms > 0),
    fps NUMERIC NOT NULL CHECK (fps > 0),
    has_audio BOOLEAN NOT NULL DEFAULT FALSE,
    profile_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (kb_name, document_id, source_sha256, profile_version)
);

CREATE TABLE IF NOT EXISTS video_segments (
    segment_id TEXT PRIMARY KEY,
    media_id TEXT NOT NULL REFERENCES video_assets(media_id) ON DELETE CASCADE,
    kb_name TEXT NOT NULL,
    document_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL CHECK (segment_index >= 0),
    start_ms BIGINT NOT NULL CHECK (start_ms >= 0),
    end_ms BIGINT NOT NULL CHECK (end_ms > start_ms),
    transcript_text TEXT NOT NULL DEFAULT '',
    visual_summary TEXT NOT NULL DEFAULT '',
    frame_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    chunk_id TEXT,
    source_sha256 TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (media_id, segment_index, source_sha256, profile_version),
    UNIQUE (media_id, start_ms, end_ms, source_sha256, profile_version)
);

CREATE INDEX IF NOT EXISTS idx_video_segments_document_order
    ON video_segments (kb_name, document_id, segment_index);
CREATE INDEX IF NOT EXISTS idx_video_segments_chunk
    ON video_segments (chunk_id) WHERE chunk_id IS NOT NULL;
