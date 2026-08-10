## ADDED Requirements

### Requirement: Default delivery checks are blocking and reproducible
The system SHALL run stable, fail-closed release checks for pull requests targeting `main`, pushes to `main`, and package-release preparation. The checks MUST validate the committed Python lock, use a frozen Python environment, use `npm ci` for the committed frontend lock, run backend tests, frontend unit tests, frontend production build, and read-only static/format checks.

#### Scenario: A pull request has a stale Python lock
- **WHEN** the committed Python dependency metadata and lock do not agree
- **THEN** the `backend-quality` or supply-chain required check SHALL fail without regenerating or committing a lockfile

#### Scenario: Frontend validation from a clean checkout
- **WHEN** the gate runs against a checkout without `node_modules`
- **THEN** it SHALL install with `npm ci`, run `test:unit`, and run the production build successfully or fail the required check

#### Scenario: Formatting requires a change
- **WHEN** a source file does not meet the configured format or static rules
- **THEN** the lint/static check SHALL fail and SHALL NOT modify or commit repository files

### Requirement: PostgreSQL migrations and key API integration are release gates
The system SHALL run a PostgreSQL service-backed, CI-only validation that applies the committed migration chain to a fresh database, repeats the chain against the same database with SQL errors treated as fatal, verifies selected schema facts, and runs a self-contained key API/CRUD integration path against real PostgreSQL.

#### Scenario: Fresh migration succeeds but repeat execution fails
- **WHEN** any committed migration fails on its second execution
- **THEN** the `postgres-migrations-api` required check SHALL fail and identify the repeat migration phase

#### Scenario: API integration only works with a mock database
- **WHEN** the key API fixture is not connected to the PostgreSQL service
- **THEN** the integration validation SHALL fail rather than treat mock or SQLite behavior as release evidence

### Requirement: Default container startup is verified independently of OpenDataLoader
The system SHALL build the Docker `default` target and verify that a started container returns a successful response from `/api/health` before a default release is accepted. This validation MUST use isolated non-secret runtime inputs and MUST capture sanitized diagnostic logs on failure.

#### Scenario: Default image cannot become healthy
- **WHEN** the default container exits or does not return a successful `/api/health` response before its startup deadline
- **THEN** the `default-container-smoke` required check SHALL fail

#### Scenario: OpenDataLoader is unavailable
- **WHEN** OpenDataLoader or Java dependencies are unavailable
- **THEN** the default container smoke SHALL not build or run the OpenDataLoader target and the default check SHALL remain independent of the opt-in workflow

### Requirement: Supply-chain evidence has explicit blocking thresholds
The system SHALL validate committed dependency locks, scan source for secrets with redacted output, scan production dependency graphs and the default image, and generate a CycloneDX SBOM for the default image. A secret finding, tool failure, missing SBOM, lock mismatch, or HIGH/CRITICAL production dependency or default-image vulnerability MUST fail the supply-chain check. Any exception MUST be version-controlled, linked to review, and have an expiry.

#### Scenario: A high-severity default image vulnerability is found
- **WHEN** the configured image scanner reports a HIGH or CRITICAL vulnerability in the default image
- **THEN** the `supply-chain-security` required check SHALL fail

#### Scenario: Secret scanning detects a credential pattern
- **WHEN** the secret scanner reports a verified finding in the configured scan scope
- **THEN** the gate SHALL fail without exposing the matching secret in logs or artifacts

### Requirement: OpenDataLoader release evidence is opt-in
The system SHALL keep OpenDataLoader Java/runtime, opt-in image, redistribution, legal approval, and specialized SBOM checks in a separately triggered workflow. Those checks MUST fail closed when invoked, but MUST NOT be a default PR or main required check.

#### Scenario: An ordinary application pull request runs default CI
- **WHEN** a pull request changes application code without explicitly invoking the OpenDataLoader release workflow
- **THEN** default required checks SHALL not install OpenDataLoader, build its image target, or require its legal evidence

#### Scenario: An OpenDataLoader release gate is explicitly invoked
- **WHEN** a maintainer dispatches the OpenDataLoader release workflow with required release evidence
- **THEN** missing lock, notice, SBOM, reconciliation, or approval evidence SHALL fail that opt-in workflow

### Requirement: Project summary quality is a formal release prerequisite
The system SHALL run `scripts/check_project_summary.py` as a blocking `project-summary-quality` check before package release preparation. CI/release documentation MUST list all stable required check names, expected durations, failure classes, retry boundaries, and the external branch-protection configuration action.

#### Scenario: Project summary quality validation fails
- **WHEN** the project summary checker returns a non-zero status
- **THEN** the project-summary check and package-release preparation SHALL fail without converting the result into an advisory warning

#### Scenario: Required checks are configured in branch protection
- **WHEN** a repository administrator binds checks in GitHub branch protection
- **THEN** the documented stable check names SHALL be used and the binding status SHALL be recorded separately from workflow implementation
