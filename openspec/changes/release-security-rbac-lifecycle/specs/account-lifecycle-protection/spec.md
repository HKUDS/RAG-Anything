## ADDED Requirements

### Requirement: User lifecycle is archive-first and auditable
The system SHALL archive or disable accounts rather than physically deleting them through administrator user-management APIs.  It SHALL preserve the account identity, lifecycle timestamps, actor, reason when supplied, and audit references.

#### Scenario: Administrator archives an account
- **WHEN** an authorized administrator archives an active non-protected account
- **THEN** the account is no longer usable for login or protected resources, remains visible to authorized audit/user-management views with lifecycle state, and an audit event records the actor and action without a password or token

### Requirement: Account security changes invalidate all sessions
The system SHALL maintain an account session generation and include it in access and refresh tokens.  It SHALL reject tokens whose generation differs from the current account generation.  Disable, archive, password replacement, and role change SHALL increment the generation atomically with the account mutation.

#### Scenario: Disabled account reuses an access token
- **WHEN** an account is disabled after receiving an access token
- **THEN** a later HTTP, SSE, WebSocket, or controlled-media authentication attempt using that token is rejected before protected data is served

#### Scenario: Password reset invalidates a refresh token
- **WHEN** an administrator resets an account password
- **THEN** a refresh request using a token issued before the reset is rejected

### Requirement: Last active super administrator is protected
The system SHALL reject archive, disable, delete-equivalent, or role-demotion operations that would leave zero active, non-archived `super_admin` accounts.  The repository SHALL enforce this invariant in the same transaction as the mutation.

#### Scenario: Attempt to disable the final super administrator
- **WHEN** an administrator attempts to disable the only active non-archived `super_admin`
- **THEN** the operation fails without changing the account or session generation and an auditable denial is recorded

#### Scenario: One of multiple super administrators is archived
- **WHEN** at least two active non-archived `super_admin` accounts exist and an authorized actor archives one of them
- **THEN** the archive succeeds and the target account sessions are invalidated
