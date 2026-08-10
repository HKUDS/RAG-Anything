## ADDED Requirements

### Requirement: Video probe gate

The video Worker SHALL validate `ffprobe` metadata before indexing a new video.
The probe result MUST include duration, fps, dimensions, codec, and audio
presence. Missing tools, timeouts, non-zero exits, invalid media, non-positive
duration/fps, and zero extracted frames MUST produce a stable retryable error
and MUST NOT create searchable video chunks.

#### Scenario: Valid video probe

- **WHEN** a new video upload has valid probe metadata and frame extraction
  succeeds
- **THEN** ingestion MUST persist the metadata and continue to segment planning

#### Scenario: Probe failure

- **WHEN** `ffprobe` is unavailable, times out, exits non-zero, or reports
  duration or fps less than or equal to zero
- **THEN** the task MUST enter a retryable video-processing failure with a
  bounded `probe_error`
- **AND** no text, vector, BM25, graph, or segment row for the video MUST be
  searchable

### Requirement: Semantic segment planning

The system SHALL plan ordered video segments using scene and timestamped ASR
boundaries when available. It MUST target 24 seconds per segment, enforce a
15-second minimum and 30-second maximum, use 3 seconds of adjacent overlap,
and emit a final tail segment. If scene or ASR boundaries are unavailable, it
MUST use the fixed-window fallback. The planned union MUST cover at least 99%
of the probed duration.

#### Scenario: Scene and ASR boundaries

- **WHEN** scene boundaries and timestamped ASR segments are available
- **THEN** each split MUST snap to the nearest boundary within six seconds when
  that keeps the segment within the configured limits
- **AND** segment indexes MUST be strictly ordered and non-empty

#### Scenario: Boundary fallback

- **WHEN** scene detection or ASR fails or returns no usable boundaries
- **THEN** the planner MUST produce deterministic fixed-window segments with the
  same limits and overlap

#### Scenario: Short and tail videos

- **WHEN** a video is shorter than the target window or has a final remainder
- **THEN** the planner MUST emit one bounded short segment or merge the tail
  without exceeding the maximum duration

### Requirement: Segment analysis and indexing

The system SHALL analyse each planned segment with up to three timestamped
frames and its local ASR text, then persist one independent text/vector/BM25
chunk and one video-segment entity. New uploads MUST NOT create an indexable
path-only block or a competing whole-video retrieval chunk. A parent summary
MAY remain as manifest/entity data but MUST NOT enter segment retrieval.

#### Scenario: Segment creates searchable evidence

- **WHEN** a planned segment has valid frames or local transcript text
- **THEN** its chunk MUST include segment index, start/end milliseconds, local
  transcript, visual summary, and an opaque controlled media reference
- **AND** its entity MUST link to the parent video document

#### Scenario: Parent manifest compatibility

- **WHEN** a new video has a whole-video summary
- **THEN** the summary MUST remain available through the parent video entity or
  manifest
- **AND** segment retrieval MUST remain the only searchable video text source

#### Scenario: Path marker isolation

- **WHEN** content separation processes a video item
- **THEN** the absolute upload path MUST remain server-side metadata only
- **AND** it MUST NOT appear as a standalone text chunk, BM25 entry, or vector
  entry

### Requirement: Retry-safe segment lifecycle

The system SHALL freeze the video indexing profile in the new upload task
snapshot. Segment IDs MUST be deterministic from source checksum, time range,
and profile version. Retrying the same task MUST upsert the same rows and MUST
not duplicate chunks, graph entities, or vectors. Deletion MUST remove the
parent's segment rows and associated searchable artifacts together.

#### Scenario: Idempotent retry

- **WHEN** a failed segment task is retried with the same snapshot and source
- **THEN** the final segment IDs and count MUST equal a single successful run

#### Scenario: Retired snapshot

- **WHEN** a task snapshot predates the new video profile
- **THEN** the Worker MUST fail the task with non-retryable
  `video_profile_retired` before RAG storage initialization
- **AND** the Worker MUST NOT silently rewrite or index the existing video
  document
