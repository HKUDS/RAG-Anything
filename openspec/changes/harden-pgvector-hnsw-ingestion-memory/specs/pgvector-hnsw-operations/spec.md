## ADDED Requirements

### Requirement: Credential-safe HNSW health inspection

The system SHALL provide a read-only operational check that discovers active
PostgreSQL HNSW vector indexes from the catalog and reports their validity,
definitions, sizes, pgvector version, VDB table counts, dead tuples, relevant
memory settings, active connections, and available memory-capacity evidence
without printing connection credentials.

#### Scenario: Runtime-created index names differ
- **WHEN** LightRAG creates HNSW indexes with implementation-specific names
- **THEN** the check SHALL discover them from `pg_catalog` rather than requiring
  a hard-coded index name

#### Scenario: Container metrics are unavailable
- **WHEN** the check cannot read cgroup or container memory metrics
- **THEN** it SHALL report that evidence as unavailable and exit successfully
  after completing its PostgreSQL read-only checks

### Requirement: Controlled HNSW maintenance procedure

The operator runbook SHALL require an upload-admission pause, task drain,
validated logical backup, capacity preflight, catalog DDL capture, transactional
non-concurrent index rebuild, and post-restart catalog/write/retrieval checks.

#### Scenario: Rebuild DDL fails
- **WHEN** an index drop/create operation fails in the maintenance transaction
- **THEN** the transaction SHALL roll back and the runbook SHALL require
  restoration of the prior runtime configuration before uploads resume

#### Scenario: External PostgreSQL deployment
- **WHEN** PostgreSQL is not the Compose-owned service
- **THEN** the runbook SHALL require DBA-provided equivalent settings and live
  verification instead of claiming Compose settings are active
