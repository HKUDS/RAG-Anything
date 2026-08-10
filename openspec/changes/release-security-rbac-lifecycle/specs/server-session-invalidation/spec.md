## ADDED Requirements

### Requirement: Account generation revokes sessions across transports
The system SHALL bind access and refresh tokens to a durable account session generation and validate that generation whenever a token authenticates HTTP, streaming, WebSocket, or controlled-media access.

#### Scenario: Role downgrade invalidates an active WebSocket reconnect
- **WHEN** an account role is downgraded after receiving a token
- **THEN** a subsequent WebSocket connection using the old token is rejected before acceptance
