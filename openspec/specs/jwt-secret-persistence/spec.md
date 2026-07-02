## MODIFIED Requirements

### Requirement: Previously issued tokens remain valid after restart
The system SHALL reject tokens issued before a server restart because the `server_start_id` has changed. The JWT signature keys persist in the database, but `server_start_id` acts as an additional session lifetime layer. Tokens issued during the current server session remain valid until their natural expiration.

#### Scenario: Previously issued tokens are rejected after restart
- **WHEN** a user holds a valid JWT access token or refresh token issued before a server restart
- **THEN** the token SHALL be rejected by the server after restart because the `server_start_id` in the token does not match the current server's `server_start_id`

#### Scenario: Tokens issued after restart are valid
- **WHEN** a user authenticates after a server restart and obtains a new JWT token
- **THEN** the token SHALL be accepted until its natural expiration time
