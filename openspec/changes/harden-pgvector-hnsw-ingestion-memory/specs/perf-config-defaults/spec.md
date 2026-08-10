## ADDED Requirements

### Requirement: HNSW recovery load profile is explicit

The Compose deployment SHALL expose the LightRAG HNSW parameters
`POSTGRES_HNSW_M=16` and `POSTGRES_HNSW_EF=64`. Its recovery profile SHALL set
`MAX_ASYNC=1` as a global LLM concurrency cap and document the independent
`ENTITY_EXTRACT_CONCURRENCY` setting.

#### Scenario: Compose-owned PostgreSQL recovery
- **WHEN** the Compose PostgreSQL service is used with the recovery profile
- **THEN** its configured cgroup limit SHALL be 4 GiB, its shared memory size
  SHALL be at least 1 GiB, and live PostgreSQL settings SHALL show
  `shared_buffers=1GB`, `work_mem=16MB`, and `maintenance_work_mem=512MB`

#### Scenario: External PostgreSQL recovery
- **WHEN** PostgreSQL is externally managed
- **THEN** the application SHALL not claim that Compose settings control that
  server and the operator SHALL verify equivalent settings separately
