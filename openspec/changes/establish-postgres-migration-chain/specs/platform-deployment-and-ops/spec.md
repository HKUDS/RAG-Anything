## ADDED Requirements

### Requirement: PostgreSQL release migration preflight
Before a production PostgreSQL schema release, operators SHALL create and verify a database backup, inspect migration status and checksum verification, review the pending migration plan, and explicitly acknowledge the backup before applying migrations. Release instructions SHALL define immediate stop, diagnostic preservation, restore, and forward-fix procedures for a migration failure.

#### Scenario: Production database preflight
- **WHEN** an operator prepares a production deployment with pending PostgreSQL migrations
- **THEN** the documented release sequence SHALL require verified backup, status, plan, acknowledged apply, and post-apply status before service deployment continues

#### Scenario: Migration preflight detects drift or a prior failure
- **WHEN** status or plan detects a checksum conflict or unresolved failed migration
- **THEN** the release procedure SHALL stop before service deployment and SHALL direct the operator to restore or follow an approved forward recovery path

### Requirement: Historical migration repairs remain release-reviewed
Any compatibility correction to an existing migration file SHALL be included in the migration-chain review and validation record before the release runner is used. Operators SHALL treat the corrected file bytes as immutable after application; later behavior changes require a new forward migration.

#### Scenario: Corrected historical migration is applied
- **WHEN** a reviewed compatibility repair is present in the manifest chain
- **THEN** the runner SHALL checksum and record that exact file content, and later edits SHALL block release on checksum drift
