## ADDED Requirements

### Requirement: HNSW memory exhaustion is terminal graph-index failure

The system SHALL recognize SQLSTATE `53200` or `Hnsw insert temporary context`
in any Worker exception wrapper as
`graph_index_hnsw_memory_exhausted`. It SHALL emit stage `graph_index`,
`retryable=false`, and a non-retry exit code.

#### Scenario: Wrapped PostgreSQL HNSW error
- **WHEN** a relationship-vector write raises a wrapped PostgreSQL out-of-memory
  exception containing SQLSTATE `53200`
- **THEN** the Worker error envelope SHALL contain
  `failure_code=graph_index_hnsw_memory_exhausted`, `stage=graph_index`, and
  `retryable=false`

### Requirement: Terminal graph-index failure cannot become degraded completion

The parent upload coordinator SHALL persist an HNSW memory failure as terminal
in upload, task, document, and retry-job state before generic failure handling.
It SHALL not complete the upload as degraded or enqueue tagging, repair, or an
automatic retry.

#### Scenario: Graph data partially exists
- **WHEN** HNSW exhaustion occurs after text chunks or graph records are written
- **THEN** the upload and processing task SHALL remain failed with
  `failure_stage=graph_index` and `retryable=false`
- **AND** no completion or degraded event SHALL be emitted

#### Scenario: Retry lease is held
- **WHEN** the failure occurs in a running upload retry job with a valid lease
- **THEN** that job SHALL be atomically marked `terminal_failed` and cleared of
  its lease so the automatic retry loop cannot claim it again

### Requirement: Explicit HNSW recovery is guarded

The retry-now action SHALL be the only path that requeues a terminal HNSW
memory failure. It SHALL reset retry state only after explicit user action and
the subsequent claimed retry SHALL execute task-scoped residue cleanup before
new indexing begins.

#### Scenario: No explicit recovery
- **WHEN** a terminal HNSW retry record exists
- **THEN** the automatic retry loop SHALL not claim it

#### Scenario: Explicit recovery succeeds after capacity restoration
- **WHEN** an authorized user invokes retry-now after capacity is restored
- **THEN** the retry job SHALL be requeued once and the completed document SHALL
  contain no duplicate chunk, entity, or relation records for its task
