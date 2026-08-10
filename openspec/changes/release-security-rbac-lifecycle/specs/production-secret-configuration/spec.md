## ADDED Requirements

### Requirement: Production authentication configuration fails closed
The system SHALL reject production startup before it serves requests when `JWT_SECRET`, `JWT_REFRESH_SECRET`, `DEFAULT_ADMIN_PASSWORD`, required PostgreSQL configuration, or credentials for an enabled model provider are missing, blank, or otherwise invalid.  Startup diagnostics MUST list only configuration variable names and MUST NOT include supplied, generated, persisted, or derived secret values.

#### Scenario: JWT secret is missing in production
- **WHEN** production configuration omits `JWT_SECRET`
- **THEN** startup fails before accepting requests and the diagnostic identifies `JWT_SECRET` without exposing any secret value

#### Scenario: Enabled provider credential is missing
- **WHEN** an enabled model provider lacks one of its required credentials
- **THEN** startup fails before accepting requests and reports only the missing variable name

### Requirement: Production secrets are externally managed
The system MUST NOT generate, print, journal, or persist fallback JWT signing keys or a default administrator password in production.

#### Scenario: Default administrator password is absent
- **WHEN** production configuration omits `DEFAULT_ADMIN_PASSWORD`
- **THEN** startup fails and no generated password or secret is emitted to stdout, stderr, logs, database settings, or audit records
