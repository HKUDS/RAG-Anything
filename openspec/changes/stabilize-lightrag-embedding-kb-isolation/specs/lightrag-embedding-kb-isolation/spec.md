## ADDED Requirements

### Requirement: Stable embedding identity
The system SHALL construct a versioned, non-secret text embedding identity containing provider/model profile, endpoint semantics fingerprint, dimension, and a collision-resistant LightRAG PostgreSQL table suffix.

#### Scenario: Canonical identity is stable
- **WHEN** the same provider profile, semantic endpoint fingerprint, and dimension are resolved twice
- **THEN** the complete identity and table suffix SHALL be byte-for-byte identical

#### Scenario: Model identity collision and length handling
- **WHEN** two model names normalize to the same PostgreSQL-safe text or exceed identifier limits
- **THEN** the suffix SHALL remain distinct through the versioned hash and SHALL fit the PostgreSQL identifier limit without secrets

### Requirement: Snapshot-bound embedding construction
The system SHALL persist `text_embedding_identity` in every new upload task snapshot and SHALL use that snapshot for Worker, retry, semantic chunking, cache, and query construction.

#### Scenario: New task snapshot
- **WHEN** an upload task is enqueued
- **THEN** its durable snapshot SHALL contain a complete text embedding identity and dimension

#### Scenario: Missing or drifted snapshot
- **WHEN** a Worker or retry loads a missing, malformed, or environment-incompatible text embedding identity
- **THEN** it SHALL fail before LightRAG initialization or writes with a deterministic non-retryable error

### Requirement: Atomic KB identity registration
The system SHALL maintain one registered text embedding identity per KB workspace and SHALL lock the registration while checking and creating it.

#### Scenario: First compatible registration
- **WHEN** a KB has no identity registration and a valid snapshot is processed
- **THEN** the system SHALL atomically register the identity before LightRAG writes

#### Scenario: Incompatible identity
- **WHEN** a populated KB is registered with a different model, endpoint fingerprint, or dimension
- **THEN** upload/query preflight SHALL fail before LightRAG initialization, writes, completion, or automatic retry

### Requirement: Workspace isolation guard
The system SHALL use `kb_dir(kb)` as the effective LightRAG workspace and SHALL reject a non-empty `PG_WORKSPACE` override unless it exactly equals that workspace.

#### Scenario: Two KBs cannot cross-read
- **WHEN** two KBs write chunks, entities, and relations with the same IDs and then query or delete
- **THEN** each operation SHALL include its own workspace and SHALL return or delete no rows belonging to the other KB

#### Scenario: Workspace override
- **WHEN** `PG_WORKSPACE` is non-empty and differs from the canonical KB workspace
- **THEN** initialization SHALL fail with an actionable workspace isolation error before any write

### Requirement: Legacy vector storage is not silently migrated
The system SHALL detect populated unsuffixed vector tables for a KB and SHALL block normal upload and query initialization without copying or re-embedding rows.

#### Scenario: Legacy table detected
- **WHEN** a KB has rows in any unsuffixed LightRAG vector table
- **THEN** preflight SHALL report an incompatible legacy storage error and SHALL leave all existing rows unchanged

### Requirement: Read-only embedding isolation diagnostics
The system SHALL expose an admin-only read-only diagnostic that discovers actual LightRAG vector tables (case-insensitively) and reports each discovered table's name, row count, and legacy status, plus registered identities, without credentials or absolute paths.

#### Scenario: Healthy diagnostic
- **WHEN** an authorized administrator requests the diagnostic
- **THEN** it SHALL execute in a read-only transaction and report all discovered chunk/entity/relation vector tables with their row counts and legacy status

#### Scenario: Unauthorized or unsafe diagnostic
- **WHEN** a caller lacks the operations permission or diagnostic SQL attempts a write
- **THEN** the request SHALL be denied and no database mutation SHALL occur
