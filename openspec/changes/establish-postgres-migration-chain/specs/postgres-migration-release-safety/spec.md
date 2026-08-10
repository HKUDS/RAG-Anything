## ADDED Requirements

### Requirement: Canonical migration chain is complete and unambiguous
The system SHALL define one checked-in ordered manifest for PostgreSQL release migrations. Each manifest entry SHALL use the complete migration filename as its immutable identifier, and the runner SHALL verify before execution that every release SQL file in `migrations/` is represented exactly once and every manifest entry resolves to a file. Numeric filename prefixes SHALL NOT be used as unique identifiers.

#### Scenario: Duplicate numeric prefixes are retained without ambiguity
- **WHEN** the manifest contains the current `001`, `009`, and `010` migration files that share numeric prefixes
- **THEN** the runner SHALL identify, order, and report each file by its complete filename without collision

#### Scenario: A migration file is absent from the manifest
- **WHEN** a release SQL file exists in `migrations/` but is not represented by the manifest
- **THEN** planning and application SHALL fail before any migration SQL is executed

### Requirement: Historical chain compatibility is explicit and bounded
The implementation MAY correct an existing migration SQL file only when a deterministic fresh or supported upgrade execution proves that the current file is incompatible with the schema or order established by earlier migrations. Each correction SHALL preserve the complete filename, intended data transformation, and reviewed dependency order; unrelated schema or business changes SHALL be introduced as new migrations.

#### Scenario: Historical SQL uses the current schema contract
- **WHEN** the complete manifest is executed against a fresh supported PostgreSQL database
- **THEN** each included historical migration SHALL use types and table names that exist at its declared position, or the chain SHALL fail closed before release

#### Scenario: A compatibility repair is proposed
- **WHEN** a historical migration requires a type, table-name, or idempotency repair
- **THEN** the repair SHALL be covered by chain tests and its raw-byte checksum SHALL become the reviewed content for future drift detection

### Requirement: Applied migrations have verifiable durable history
The system SHALL store PostgreSQL migration history with the immutable migration ID, manifest sequence, SHA-256 checksum of the exact file bytes, terminal state, and execution timestamps. The runner SHALL provide a queryable status output that reports the ordered local chain and its applied/failed/unknown state without revealing credentials, DSNs, or secret values.

#### Scenario: Fresh installation records the full chain
- **WHEN** the runner applies the complete manifest to a fresh supported PostgreSQL database
- **THEN** history SHALL contain one applied row for every manifest entry with its sequence and SHA-256 checksum

#### Scenario: An applied migration changes on disk
- **WHEN** a history row records an applied migration and its current file bytes produce a different SHA-256 checksum
- **THEN** verification and application SHALL stop before executing any later migration and SHALL report a sanitized checksum conflict

### Requirement: Upgrade and repeat execution are safe and deterministic
The runner SHALL apply only migrations missing from valid applied history, in manifest sequence. A supported historical database upgrade SHALL execute the remaining chain in order. Repeating a successful runner invocation SHALL execute no migration SQL and SHALL preserve the recorded history.

#### Scenario: Upgrade from a supported historical checkpoint
- **WHEN** a database has validated history through a supported manifest checkpoint
- **THEN** the runner SHALL apply every later manifest entry exactly once and record them in sequence

#### Scenario: Repeating a completed migration run
- **WHEN** the same complete migration manifest is applied again with matching checksums
- **THEN** the runner SHALL report that the chain is current and SHALL not re-execute any migration file

### Requirement: Migration failure stops the release path
The runner SHALL stop at the first malformed, checksum-conflicting, or SQL-failing migration and SHALL NOT invoke a later migration. It SHALL return non-zero, preserve a sanitized failure record/status, and SHALL NOT mark the failing migration applied. It SHALL NOT classify generic SQL text such as `already exists` as success.

#### Scenario: Intentional migration failure
- **WHEN** a migration returns a non-zero database execution result
- **THEN** the runner SHALL return failure, record/report the failed migration, and leave every later migration unexecuted

#### Scenario: A previously failed migration is encountered
- **WHEN** migration history contains an unresolved failed record
- **THEN** a later runner invocation SHALL stop before applying subsequent migrations and SHALL instruct the operator to remediate or restore according to the release runbook

### Requirement: Release application requires a backup-aware preflight
The release command SHALL provide status and plan/verification modes and SHALL require explicit backup acknowledgement before it applies migration SQL. The migration documentation SHALL require a verified backup before a production upgrade and SHALL define failure handling and rollback as restore from that backup or a separately reviewed forward corrective migration.

#### Scenario: Apply is invoked without backup acknowledgement
- **WHEN** an operator invokes the migration apply command without the required acknowledgement
- **THEN** the command SHALL exit before connecting for migration execution and SHALL display the backup/preflight requirement without exposing secrets

#### Scenario: Release preflight succeeds
- **WHEN** an operator has a verified backup, matching migration checksums, no unresolved failure, and a valid complete manifest
- **THEN** plan/status SHALL show the exact pending migration identifiers and apply SHALL be eligible to run

### Requirement: Migration validation is reproducible
The repository SHALL include automated tests for fresh installation, supported historical upgrade, repeated execution, checksum drift, and an intentionally failing migration. The test suite SHALL include an opt-in isolated PostgreSQL integration path suitable for CI and SHALL redact database connection secrets from output.

#### Scenario: CI-equivalent PostgreSQL integration run
- **WHEN** `MIGRATION_TEST_DATABASE_URL` is configured for an isolated PostgreSQL test target
- **THEN** the integration suite SHALL execute the real runner scenarios for fresh install, upgrade, repeat execution, and intentional failure and SHALL clean only its generated test namespace
