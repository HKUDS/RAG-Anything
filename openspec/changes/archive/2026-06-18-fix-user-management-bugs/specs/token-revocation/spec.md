## ADDED Requirements

### Requirement: Logout revokes refresh token family

When a user logs out, the system SHALL revoke the associated refresh token family (`rfam`) so that the refresh token cannot be used to obtain new access tokens.

#### Scenario: Logout with refresh token in body
- **WHEN** `POST /api/auth/logout` is called with a valid `refresh_token` in the request body
- **THEN** the refresh token's `jti` SHALL be revoked
- **AND** the refresh token family (`rfam`) SHALL be revoked
- **AND** subsequent use of the refresh token SHALL return HTTP 401

#### Scenario: Logout without refresh token in body
- **WHEN** `POST /api/auth/logout` is called without a `refresh_token` in the body
- **THEN** only the access token's `jti` SHALL be revoked (backward compatible)

### Requirement: Token revocations persist across server restarts

Token revocation entries SHALL be stored in a persistent `token_revocations` table in SQLite, and SHALL be reloaded on application startup.

#### Scenario: Revoked token remains revoked after restart
- **WHEN** a token is revoked via logout
- **AND** the server is restarted
- **THEN** the same token SHALL still be rejected (HTTP 401)

#### Scenario: Expired revocation entries are cleaned up
- **WHEN** a revocation entry's `expires_at` timestamp is in the past
- **THEN** the entry SHALL be removed from the `token_revocations` table during periodic cleanup

### Requirement: Token blacklist is shared across worker processes

In a multi-worker deployment, token revocation SHALL be visible to all worker processes through the shared SQLite database.

#### Scenario: Token revoked on worker A is rejected on worker B
- **WHEN** a token is revoked on worker A via `/api/auth/logout`
- **THEN** a subsequent request with the same token to worker B SHALL return HTTP 401
