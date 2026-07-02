## ADDED Requirements

### Requirement: Per-KB processing queue
The system SHALL maintain a per-KB FIFO queue of pending file processing tasks. Both single-file (`POST /api/upload/file`) and batch (`POST /api/upload/files`) upload endpoints SHALL add files to this queue instead of spawning background workers directly.

#### Scenario: Single file added to queue
- **WHEN** a file is uploaded via `POST /api/upload/file` to KB "X"
- **THEN** the file is added to KB "X"'s processing queue and the endpoint returns 202 with `{"status": "queued", "position": <N>}`

#### Scenario: Batch files added to queue
- **WHEN** 13 files are uploaded via `POST /api/upload/files` to KB "X"
- **THEN** all 13 files are added to KB "X"'s processing queue, and the endpoint returns 202 with `{"status": "queued", "total": 13}`

#### Scenario: Queue shared across endpoints
- **WHEN** file A is uploaded via `POST /api/upload/file` and immediately file B is uploaded via `POST /api/upload/files` to the same KB
- **THEN** both files are added to the same queue and processed in order

#### Scenario: Different KBs have independent queues
- **WHEN** file A is uploaded to KB "X" and file B is uploaded to KB "Y"
- **THEN** file B is processed independently, without waiting for KB "X"'s queue

### Requirement: Queue drain processes files sequentially
A single drain coroutine per KB SHALL process files from the queue one at a time. The drain SHALL be started automatically when the first file is added to an empty queue, and SHALL exit when the queue becomes empty.

#### Scenario: Drain starts on first file
- **WHEN** a file is added to an empty queue for KB "X"
- **THEN** the drain coroutine starts automatically and begins processing the file

#### Scenario: Sequential processing
- **WHEN** files [A, B, C] are in KB "X"'s queue with `max_concurrent_files` = 1
- **THEN** file A is processed first, then B, then C — never two at once

#### Scenario: Next file starts after completion
- **WHEN** file A completes processing (worker exits with code 0)
- **THEN** file B's processing begins automatically

#### Scenario: Next file starts after failure
- **WHEN** file A fails during processing (worker exits with non-zero code)
- **THEN** file B's processing begins automatically

#### Scenario: Drain exits on empty queue
- **WHEN** the last file in the queue completes processing
- **THEN** the drain coroutine exits, and the KB's queue returns to idle state

### Requirement: Queue position feedback
The upload response SHALL include the file's position in the queue so the frontend can display estimated wait time.

#### Scenario: Position reported for queued file
- **WHEN** a file is uploaded and the queue already has N pending files
- **THEN** the response includes `{"position": N+1, "queue_size": N+1}`

#### Scenario: Position is 1 for empty queue
- **WHEN** a file is uploaded to an idle KB (queue was empty)
- **THEN** the response includes `{"position": 1, "queue_size": 1}`

### Requirement: Configurable concurrency limit
The per-KB concurrency limit SHALL be configurable via the `MAX_CONCURRENT_FILES` environment variable (default: 1).

#### Scenario: Default single-worker behavior
- **WHEN** `MAX_CONCURRENT_FILES` is not set
- **THEN** only 1 file is processed at a time per knowledge base

#### Scenario: Custom concurrency level
- **WHEN** `MAX_CONCURRENT_FILES` is set to 3
- **THEN** up to 3 files may be processed concurrently per knowledge base

### Requirement: Queue is in-memory only
The processing queue SHALL be stored in-memory (not persisted). Server restarts SHALL clear the queue.

#### Scenario: Queue lost on restart
- **WHEN** the server is restarted while files are queued
- **THEN** the queue is cleared; uploaded files on disk remain but will not be automatically re-processed
