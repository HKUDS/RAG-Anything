## Why

Current video ingestion creates an indexed path marker plus one whole-video
summary.  The summary loses procedural timing, can be truncated, and may show
zero duration metadata even when the video was analysed.  Teachers and
students cannot retrieve an operation step and jump to the corresponding part
of an instructional video.

## What Changes

- Replace indexable video path markers with time-bounded semantic video
  segments for newly uploaded videos.
- Require successful media probing before video indexing; a failed probe
  creates a retryable processing failure rather than an empty or zero-duration
  chunk.
- Preserve scene and ASR timing, create deterministic segment records, and
  expose protected time anchors in citations and the source UI.
- Freeze the v2 segmenting profile in the existing upload task snapshot. New
  uploads are v2-only; completed historical uploads are not backfilled.

## Capabilities

### New Capabilities

- `video-semantic-segmentation`: Time-aware video segment planning,
  persistence, indexing, and retry-safe lifecycle handling.
- `video-segment-citations`: Authorized video time anchors in query citations
  and the source playback UI, backed by a controlled video asset catalog.

### Modified Capabilities

- `video-audio-transcription`: Preserve timestamped Whisper segments alongside
  the transcript text.
- `video-knowledge-graph`: Store video segment entities and segment chunks
  instead of an indexable whole-video path/summary chunk.
- `citation-structured-output`: Include optional video timing and controlled
  media data without changing existing citation fields.

## Impact

The change affects video parsing and multimodal batching, upload settings
snapshots, PostgreSQL migrations, chunk/source enrichment, and the React
source citation surface. It requires `ffmpeg` and `ffprobe` in every Worker
runtime that enables video processing.
