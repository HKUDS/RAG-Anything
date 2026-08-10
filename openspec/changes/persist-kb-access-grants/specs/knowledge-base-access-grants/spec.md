## ADDED Requirements

### Requirement: Knowledge-base grants are durable and scoped
The system SHALL persist an explicit per-user knowledge-base grant separately from roles and KB ownership.  A grant SHALL supply KB scope only; it SHALL NOT confer `kb:read`, `kb:write`, or any administrative permission.

#### Scenario: Grant is projected after a new login
- **WHEN** an administrator has granted a user access to an existing KB and that user authenticates
- **THEN** the authenticated user projection SHALL include that KB in `allowed_kbs`

#### Scenario: Revocation takes effect for an existing session
- **WHEN** an administrator removes a user's grant
- **THEN** the user's prior session SHALL be invalidated and later authenticated requests SHALL no longer receive the revoked KB in `allowed_kbs`

### Requirement: Grant mutation is authorized and validated
Only a caller with `users:write` SHALL replace another user's grant set.  The system SHALL validate every submitted KB name exists, persist the replacement atomically, and record an audit event without credentials or token values.

#### Scenario: Authorized administrator replaces grants
- **WHEN** a `users:write` caller submits an existing-KB list for a target user
- **THEN** the system SHALL persist exactly that list, return the sanitized user representation, and invalidate the target's sessions

#### Scenario: Unknown KB is rejected without partial mutation
- **WHEN** a caller submits at least one KB name that does not exist
- **THEN** the system SHALL return a validation error and preserve the target user's prior grants

#### Scenario: Unauthorized caller cannot mutate grants
- **WHEN** a caller without `users:write` submits a user update containing `allowed_kbs`
- **THEN** the system SHALL return 403 and make no grant change
