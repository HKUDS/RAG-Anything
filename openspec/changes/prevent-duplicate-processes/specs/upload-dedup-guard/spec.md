## ADDED Requirements

### Requirement: Duplicate upload detection
The upload API SHALL reject upload requests for a file that is already being processed in the same knowledge base, returning HTTP 409 Conflict.

#### Scenario: First upload accepted
- **WHEN** a file is uploaded to KB "X" and no existing task is processing the same file
- **THEN** the upload is accepted and returns 202 Accepted with a task ID

#### Scenario: Duplicate upload rejected
- **WHEN** a file is uploaded to KB "X" and an active processing task already exists for the same file hash in the same KB
- **THEN** the server returns HTTP 409 Conflict with a JSON body containing `{"detail": "File is already being processed", "existing_task_id": "<task_id>"}`

#### Scenario: Same filename in different KBs allowed
- **WHEN** the same file is uploaded to KB "X" and KB "Y" simultaneously
- **THEN** both uploads are accepted (different KBs are independently processed)

#### Scenario: Duplicate after previous task completed
- **WHEN** a file is uploaded that was previously processed and the task has completed (status is "completed" or "failed")
- **THEN** the upload is accepted as a new task

### Requirement: File hash based dedup key
The deduplication SHALL use the tuple `(kb_name, sha256(file_content)[:16])` as the lookup key, not the filename alone.

#### Scenario: Same content, different filename
- **WHEN** two files with different names but identical content are uploaded to the same KB
- **THEN** the second upload is rejected with 409 Conflict (same content hash)

#### Scenario: Different content, same filename
- **WHEN** two different files with the same filename are uploaded to the same KB sequentially
- **THEN** each upload is independently processed (different content hash)

### Requirement: Dedup status reflected in WebSocket progress
The WebSocket progress broadcast SHALL include the duplicate status so the frontend can display it.

#### Scenario: Duplicate detected during processing
- **WHEN** a duplicate upload is detected
- **THEN** the WebSocket message includes `{"type": "duplicate", "file": "<filename>", "existing_task_id": "<id>"}`
