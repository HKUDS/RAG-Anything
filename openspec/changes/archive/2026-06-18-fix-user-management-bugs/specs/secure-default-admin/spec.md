## ADDED Requirements

### Requirement: No hardcoded default admin password

The system SHALL NOT contain a hardcoded default admin password in source code. If `DEFAULT_ADMIN_PASSWORD` environment variable is not set and no admin user exists, the system SHALL generate a cryptographically random password.

#### Scenario: Fresh install generates random password
- **WHEN** `init_db()` runs with no existing admin user and no `DEFAULT_ADMIN_PASSWORD` env var
- **THEN** the system SHALL generate a random password using `secrets.token_urlsafe(16)` and print it to stderr

#### Scenario: Production deployment with env var uses provided password
- **WHEN** `init_db()` runs with `DEFAULT_ADMIN_PASSWORD` env var set
- **THEN** the system SHALL use the provided password for the default admin

### Requirement: Default admin must change password on first login

When a default admin account is created by `init_db()`, the system SHALL set `must_change_password = 1` on that account.

#### Scenario: Default admin forced to change password
- **WHEN** the auto-created default admin logs in for the first time
- **THEN** the login response SHALL include `must_change_password: true`
- **AND** the frontend SHALL require password change before allowing other actions

### Requirement: `init_db()` creates all required tables

The `init_db()` function SHALL create `roles`, `audit_logs`, and `token_revocations` tables (using `IF NOT EXISTS`) in addition to existing `users` and `settings` tables.

#### Scenario: Fresh install has all tables
- **WHEN** `init_db()` runs against an empty database
- **THEN** the database SHALL contain `users`, `settings`, `roles`, `audit_logs`, and `token_revocations` tables
