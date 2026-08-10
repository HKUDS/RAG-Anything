## MODIFIED Requirements

### Requirement: Queue is in-memory only
The processing queue SHALL be reconstructed from durable upload state after restart and SHALL never create two active processors for one task. A database interruption SHALL not be interpreted as a claim loss or as permission to enqueue a second processor.

#### Scenario: Queue reconstructed after restart
- **WHEN** the server starts with durable uploads in `queued`, `processing`, or `retry_wait`
- **THEN** the durable scanner enqueues only tasks that can be atomically claimed by their owner/generation

#### Scenario: Transient database interruption
- **WHEN** a claim or heartbeat query cannot reach PostgreSQL
- **THEN** the exception is retried with backoff and no second processor is created for that task

#### Scenario: Successful fencing update affects zero rows
- **WHEN** a claim-qualified SQL update succeeds with `UPDATE 0`
- **THEN** the current processor stops and the task is not processed again by that processor
