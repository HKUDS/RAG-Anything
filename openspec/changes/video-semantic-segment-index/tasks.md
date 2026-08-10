## 1. Contracts and storage

- [x] 1.1 Add the versioned video segment settings to immutable upload task snapshots.
- [x] 1.2 Add `029_video_semantic_segments.sql` and update `migration_manifest.json` with video asset/segment tables, deterministic uniqueness, indexes, and cascade cleanup.
- [x] 1.3 Add repository/service methods for segment upsert, listing, deletion, and retry cleanup.

## 2. Probe, ASR, and planning

- [x] 2.1 Add a strict Worker ffmpeg/ffprobe probe gate with stable retryable error codes and bounded `probe_error` metadata.
- [x] 2.2 Extend Whisper transcription to retain timestamped segments while preserving merged-text compatibility.
- [x] 2.3 Implement scene/ASR boundary planning with 24s target, 15-30s bounds, 3s overlap, tail handling, and 99% coverage validation.
- [x] 2.4 Add deterministic segment IDs from source checksum, time range, and profile version.

## 3. Multimodal indexing

- [x] 3.1 Remove the video path marker from ordinary text separation and regression-test text/BM25/vector isolation.
- [x] 3.2 Refactor video analysis to produce per-segment local transcript, up to three frames, visual summary, and controlled `media_id` references; retain the parent summary only as manifest/entity data.
- [x] 3.3 Integrate segment chunks/entities into multimodal batching, document status, vector/BM25 storage, and belongs-to relations.
- [x] 3.4 Ensure retry, failure cleanup, deletion, and v2-only profile retirement behavior are consistent and idempotent.
- [x] 3.5 Retire the legacy processor and whole-video chunk template; reject incomplete legacy, missing, and unknown video snapshots with `video_profile_retired`.

## 4. Retrieval and UI

- [x] 4.1 Enrich chunk/source and non-stream/SSE citation payloads with authorized video segment timing.
- [x] 4.2 Deduplicate parent video results while retaining ordered adjacent segment hits.
- [x] 4.3 Connect the existing controlled media/source UI to render segment time ranges and seek to the start time.
- [x] 4.4 Add controlled video media delivery with `media_id`, KB ownership checks, Range support, 403/404 handling, and no local path disclosure.

## 5. Verification and project records

- [x] 5.1 Add focused unit tests for probe failures, boundary fallbacks, coverage, segment IDs, and retry idempotency.
- [ ] 5.2 Add authenticated PostgreSQL/Worker/query/SSE integration coverage and the four battery procedure retrieval cases.
- [ ] 5.3 Verify the sample MP4 with the actual Worker runtime and confirm ffmpeg/ffprobe availability, segment count, and time metadata.
- [ ] 5.4 Run focused/full validation, OpenSpec strict validation, diff checks, and update `PROJECT_SUMMARY.md` with current facts and this task record.
