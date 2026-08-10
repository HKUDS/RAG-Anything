## ADDED Requirements

### Requirement: Formal production backup asset boundary
The operations package SHALL declare a production backup inventory that identifies PostgreSQL, `rag_storage`, `uploads`, `output`, selected deployment configuration, and model artifacts. The inventory SHALL state for each asset whether it is included, reproducible externally, or owned by another system. Redis and every external graph/vector store SHALL be explicitly classified as recoverable, rebuildable, or externally owned; they MUST NOT be silently assumed to be covered by an application backup.

#### Scenario: Deployment declares external vector storage
- **WHEN** an operator configures an external vector or graph store
- **THEN** the inventory records the owner and required native backup/restore contract
- **AND** the application bundle does not claim that the external store is restored

#### Scenario: Local model directory is excluded by policy
- **WHEN** local model weights are not approved for backup
- **THEN** the manifest records the model asset as externally reproducible
- **AND** no model content is copied into the bundle

### Requirement: Secret-safe verifiable backup bundle
The backup tooling SHALL create a timestamped bundle outside live runtime paths and SHALL emit a manifest plus SHA-256 checksums for every bundle artifact. The manifest SHALL contain only non-sensitive metadata needed to verify and restore the bundle. The tooling MUST NOT print or write database passwords, DSNs, API keys, tokens, secret configuration values, user content, or user identifiers.

#### Scenario: Successful backup verification
- **WHEN** a backup completes with all declared assets available
- **THEN** the bundle contains a PostgreSQL logical dump, declared file archives, `manifest.json`, and a checksum file
- **AND** a verification command reports every checksum as valid

#### Scenario: Backup command encounters a secret-bearing connection string
- **WHEN** the database connection is supplied through deployment configuration
- **THEN** command output redacts the connection source
- **AND** neither the manifest nor the log contains the secret-bearing value

### Requirement: First-release recovery objective and retention policy
The operations package SHALL define RPO <= 24 hours and RTO <= 2 hours for the initial supported production topology. It SHALL require daily full backup completion, at least 35 daily and 12 monthly retained recovery points, encrypted off-site copy completion within 24 hours, least-privilege access, and quarterly isolated restore drills. A deployment MUST NOT claim compliance until a drill evidence record includes measured RPO and RTO.

#### Scenario: Backup freshness exceeds the RPO
- **WHEN** the newest verified backup is older than 24 hours
- **THEN** the operations alert contract raises a backup-freshness incident
- **AND** the runbook directs the operator to investigate before the next release window

#### Scenario: Restore drill does not meet the RTO
- **WHEN** an isolated restore takes longer than two hours
- **THEN** the drill evidence marks the recovery objective as not met
- **AND** the runbook requires an escalation and remediation plan

### Requirement: Isolated restoration and semantic validation
The restore tooling SHALL verify the source bundle before extraction and SHALL restore only into an explicit isolated target root and isolated PostgreSQL target. It SHALL refuse unsafe target paths and SHALL not overwrite a populated target without an explicit confirmation flag. A validation command SHALL verify, without exposing user data, PostgreSQL/RBAC, audit availability, KB metadata/workspaces, upload-file references, and controlled-media references beneath restored output roots.

#### Scenario: Restored upload and media references are valid
- **WHEN** the backup is restored into an isolated target
- **THEN** validation compares persisted upload references against the restored upload directory
- **AND** it confirms controlled media references resolve under declared restored output roots

#### Scenario: Unsafe restore target is supplied
- **WHEN** an operator supplies a target outside the declared isolation root or a non-empty target without confirmation
- **THEN** the restore command exits without extracting or invoking database restore
- **AND** it reports the violated safety precondition without secrets
