## ADDED Requirements

### Requirement: Authorized users can delete unfinished upload tasks
The system SHALL allow a user with `kb:write` permission and access to the target knowledge base to delete only that user's `queued`, `processing`, or `retry_wait` upload task. Completed, failed, degraded, and deleted tasks SHALL retain their existing document lifecycle behavior.

#### Scenario: Processing task deletion is accepted
- **WHEN** an authorized user deletes a `processing` task in an accessible knowledge base
- **THEN** the service SHALL atomically expose `cancelling` before stopping task execution and return either its completed deletion or a pollable cancellation response

#### Scenario: Task visibility is enforced
- **WHEN** a user requests deletion for a task outside the user's knowledge-base or uploader scope
- **THEN** the service SHALL return the existing not-found response and SHALL not alter execution or stored content

### Requirement: Cancellation prevents task resurrection
The system SHALL prevent a cancelled task's worker, retry runner, task-state writer, or startup recovery from changing `cancelling` or `deleted` back to a runnable or terminal upload state.

#### Scenario: Late worker completion
- **WHEN** a worker reports success or failure after its task entered `cancelling`
- **THEN** the service SHALL not persist completion, failure, progress, or an automatic retry for that task

#### Scenario: Retry wait deletion
- **WHEN** a `retry_wait` task is deleted
- **THEN** the system SHALL cancel its retry job before it can reclaim or requeue the upload

### Requirement: Cancellation cleans only task-owned content
The system SHALL clean staged files, task state, retry state, settings snapshots, and partially produced knowledge-base content only when durable task provenance matches the cancellation target.

#### Scenario: Partial document cleanup
- **WHEN** a cancelled task has produced a document whose task ID or file-hash provenance matches the upload
- **THEN** the system SHALL remove its document index, vectors, caches, tag and repair work, and controlled artifacts before marking the upload deleted

#### Scenario: Same-name document isolation
- **WHEN** another upload in the same knowledge base has the same filename but different task provenance
- **THEN** cancelling the target task SHALL not remove the other upload's document or artifacts

### Requirement: Cancellation progress is pollable
The deletion endpoint SHALL return `202` with `status: cancelling` while cancellation cleanup is still in progress and SHALL return `200` with `status: deleted` only after cleanup completes. Repeated deletion requests for `cancelling` SHALL be idempotent.

#### Scenario: Bounded wait expires
- **WHEN** the worker or cleanup coordinator does not finish within its bounded wait
- **THEN** the service SHALL preserve `cancelling`, retain deduplication ownership, and return a pollable `202` response

#### Scenario: Repeated cancellation request
- **WHEN** a user repeats deletion for the same `cancelling` task
- **THEN** the service SHALL return `202` without terminating another task or releasing cleanup resources early

### Requirement: The document list routes unfinished uploads by durable task provenance
The document-list API SHALL include an `upload_task_id` for a persisted row
when its task provenance is available from the document status record, and for
a processing-only row from that row's task ID. It SHALL also return a
server-derived `can_cancel_upload` flag from the visible durable upload state.
The document table SHALL use that ID when this flag is true. If an explicit
durable task ID is present and the displayed document health is `queued`,
`processing`, or `retry_wait`, it MAY also send the task-deletion request when
the capability flag is absent or stale; the service SHALL remain the final
authority for uploader scope and task state. The table SHALL not derive task
ownership from filenames. Its confirmation dialog SHALL render through the
shared viewport-centered portal.

#### Scenario: Same-name upload isolation in the document list
- **WHEN** two task records use the same filename and one persisted document
  row has a durable task ID
- **THEN** the document row SHALL expose its own task ID and deletion SHALL not
  target the other task

#### Scenario: Processing deletion begins from the document table
- **WHEN** an authorized user confirms deletion of a `processing` document
  row with an `upload_task_id`
- **THEN** the table SHALL request deletion of that upload task, retain the row
  after a `202 cancelling` response, and show that stopping and cleanup are in
  progress until polling removes it

#### Scenario: Document-list capability is stale
- **WHEN** a row has an explicit `upload_task_id`, shows `queued`, `processing`,
  or `retry_wait`, and its `can_cancel_upload` capability is absent or false
- **THEN** the table MAY request deletion for that exact task ID and the service
  SHALL enforce the final uploader, knowledge-base, and task-state checks
