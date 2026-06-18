## ADDED Requirements

### Requirement: Audit log write failures are not silently discarded

When the audit log flush operation fails, the system SHALL log the error, retain the failed entries in the queue for retry, and expose a health metric.

#### Scenario: DB write failure triggers error logging
- **WHEN** the `_flush()` method encounters a write error (e.g., disk full, permission denied)
- **THEN** the error SHALL be logged at ERROR level with the batch size and error details
- **AND** the failed entries SHALL be re-queued for the next flush attempt (not discarded)

#### Scenario: Queue is not cleared before successful write
- **WHEN** `_flush()` runs
- **THEN** the in-memory queue SHALL NOT be cleared until after `conn.commit()` succeeds

### Requirement: Audit log health is monitorable

The system SHALL expose audit logger health status including queue depth, consecutive failure count, and last successful flush timestamp.

#### Scenario: Health endpoint reports audit status
- **WHEN** `GET /admin/health/audit` is called by an admin
- **THEN** the response SHALL include `queue_depth`, `consecutive_failures`, and `last_successful_flush`

#### Scenario: Consecutive failures trigger alert threshold
- **WHEN** the audit logger experiences 5 or more consecutive write failures
- **THEN** a CRITICAL log message SHALL be emitted
