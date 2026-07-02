## ADDED Requirements

### Requirement: Server start ID embedded in JWT tokens
The system SHALL generate a unique server start identifier on each startup and embed it in all issued JWT access tokens and refresh tokens.

#### Scenario: Server start ID included in access token
- **WHEN** a user successfully authenticates via `/api/auth/login`
- **THEN** the issued JWT access token SHALL contain a `sid` claim with the current server start ID

#### Scenario: Server start ID included in refresh token
- **WHEN** a user successfully authenticates via `/api/auth/login`
- **THEN** the issued refresh token SHALL contain a `sid` claim with the current server start ID

#### Scenario: Refreshed tokens carry current server start ID
- **WHEN** a user refreshes their token via `/api/auth/refresh`
- **THEN** the newly issued access and refresh tokens SHALL contain the current server start ID

### Requirement: Token rejected when server start ID mismatches
The system SHALL reject any JWT token whose `sid` claim does not match the current server start ID.

#### Scenario: Token from previous server instance rejected
- **WHEN** a request includes a valid JWT token issued before a server restart
- **THEN** the system SHALL reject the token as invalid because its `sid` does not match the current server start ID

#### Scenario: Token from current server instance accepted
- **WHEN** a request includes a valid JWT token issued during the current server session
- **THEN** the system SHALL accept the token because its `sid` matches the current server start ID

#### Scenario: Token without sid claim rejected
- **WHEN** a request includes a JWT token that lacks the `sid` claim (issued before this feature was deployed)
- **THEN** the system SHALL reject the token as invalid

### Requirement: Server start ID is ephemeral
The system SHALL NOT persist the server start ID; it SHALL exist only in process memory.

#### Scenario: Server start ID lost on restart
- **WHEN** the server process restarts
- **THEN** a new server start ID SHALL be generated, and all tokens from the previous session SHALL be rejected
