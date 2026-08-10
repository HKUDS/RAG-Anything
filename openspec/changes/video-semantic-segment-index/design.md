## Context

The parser emits one `{type: "video", video_path}` item, while content
separation also adds a path-only text marker. The multimodal batch processor
calls the video processor once per item. The processor currently samples a few
frames and combines a whole transcript into one description; `SceneDetector`
is not used by this path and Whisper returns no segment timings. LightRAG's
fixed chunk records also do not provide a durable place for video timing or a
protected media reference.

## Goals / Non-Goals

**Goals:**

- Make only new video uploads produce deterministic, independently retrievable
  procedural segments with valid timing metadata.
- Keep path markers out of text, BM25, and vector indexes.
- Fail closed and retry when media probing or required frame extraction fails.
- Preserve upload snapshot immutability, PostgreSQL/RAG chunk consistency,
  and RBAC-controlled media access while retiring the legacy video processor.

**Non-Goals:**

- No automatic re-indexing of existing video documents.
- No new user-facing video model controls or live-stream processing.
- No automatic re-indexing or deletion of completed historical video chunks.

## Decisions

### 1. Segment contract and persistence

Create `video_assets` and `video_segments` PostgreSQL tables through
`029_video_semantic_segments.sql`. `video_assets` owns `media_id`, `kb_name`,
`doc_id`, source checksum, and a server-side controlled asset root. The
segment table has
`segment_id`, `doc_id`, `kb_name`, `segment_index`, `start_ms`, `end_ms`,
`duration_ms`, `transcript_text`, `visual_summary`, `frame_refs`,
`media_ref`, `chunk_id`, `profile_version`, `source_sha256`, and lifecycle
timestamps and references the parent `media_id`. Keyframes are registered in
the same controlled catalog before a task completes. `segment_id` is
deterministic from the source checksum, time range, and profile version; a
unique constraint makes retries idempotent.
Keep the raw upload path server-side only. Chunk/source DTOs carry the opaque
`media_ref`, times, and document identity, never an absolute path.

### 2. Boundary algorithm

Probe duration, fps, dimensions, codec, and audio with `ffprobe`. Obtain
timestamped ASR segments when audio is available and scene boundaries when
scene detection succeeds. Plan ordered windows using target 24 seconds,
minimum 15 seconds, maximum 30 seconds, and 3 seconds overlap. Snap a split to
the nearest valid scene or ASR boundary within six seconds; otherwise use the
target window. Always emit a final tail window and verify union coverage is at
least 99% of the probed duration. Empty ASR or scene results use the fixed
window fallback.

### 3. Analysis and indexing

Select up to three frames per window (start, midpoint, and nearest detected
boundary), analyse them with the existing VLM semaphore, and prompt for the
step, objects/tools, measurements, safety conditions, and time-local evidence.
Each segment becomes one text/vector/BM25 chunk and one segment entity linked to
the parent video entity. Do not create a competing full-video retrieval chunk;
the parent is a manifest/graph record only.

### 4. Failure and snapshot semantics

Video-enabled Worker startup accepts only the explicit `v2` profile and
validates `ffmpeg` and `ffprobe`. A missing, legacy, or unknown profile fails
terminally with `video_profile_retired` before RAG storage initialization and
instructs the user to upload again. A missing tool,
probe timeout/non-zero result, non-positive duration/fps, or zero extracted
frames returns stable retryable error metadata and cleans partial segment,
vector, graph, and media rows. New upload settings snapshots include
`video_index_profile_version="v2"` and all segmenting limits. The legacy
processor and whole-video chunk template are removed; no backfill is run.

### 5. Retrieval and playback

Enrich retrieved chunks and SSE/non-stream citations with optional
`video_segment` data: `segment_id`, `start_ms`, `end_ms`, `media_id`,
`media_kb`, and an authorized controlled-media URL. Deduplicate by parent
video while retaining adjacent segments. The existing citation/source UI
renders a compact time-range action and seeks the protected video source after
the normal KB permission check. The endpoint supports HTTP Range and returns
403/404 without leaking a filesystem path.

### Alternatives considered

- Fixed-size-only chunks were rejected because scene/ASR boundaries are needed
  for procedural steps.
- A single JSON manifest in `doc_status` was rejected because it cannot be
  queried or constrained safely across retries and chunk deletion.
- Full-video summaries remain as a parent video entity/manifest for new
  uploads, but are not inserted as a competing vector/BM25 chunk.

## Risks / Trade-offs

- **VLM/ASR cost:** up to three frame calls per segment; bounded segment size,
  frame count, and per-video concurrency cap the cost.
- **Boundary noise:** scene detection can over-segment; minimum/maximum window
  limits and a six-second snap radius keep segments useful.
- **Provider/runtime variance:** missing native tools or model failures can
  delay ingestion; stable retryable task codes and cleanup prevent false
  success.
- **Historical inconsistency:** completed old video chunks remain whole-video/
  path based and are not reprocessed. Incomplete legacy jobs are cancelled
  during rollout; a post-deployment race becomes `video_profile_retired`.

## Migration Plan

1. Apply the new PostgreSQL migration and deploy Worker dependencies before
   enabling the new profile for new uploads.
2. Before deployment, cancel `queued`, `processing`, and `retry_wait` video
   tasks whose snapshots are not explicitly v2 using the existing cancellation
   flow. Completed historical chunks are left untouched.
3. Roll out backend and Worker together. Any legacy job that races deployment
   fails terminally with `video_profile_retired`; rollback restores the prior
   deployment rather than selecting a legacy processor at runtime.

## Open Questions

None for this implementation. The exact migration filename must follow the
current manifest's next sequence number at implementation time.
