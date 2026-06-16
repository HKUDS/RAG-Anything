## ADDED Requirements

### Requirement: JWT secret keys persist across server restarts
The system SHALL store JWT signing keys (`jwt_secret`, `jwt_refresh_secret`) in a persistent storage so that previously issued tokens remain valid after the server restarts.

#### Scenario: First startup generates and persists keys
- **WHEN** the server starts for the first time with no `JWT_SECRET` environment variable set
- **THEN** the system SHALL generate cryptographically random secret keys, store them in the `settings` table of `auth.db`, and use them for JWT signing

#### Scenario: Subsequent startup loads persisted keys
- **WHEN** the server restarts and `JWT_SECRET` environment variable is not set
- **THEN** the system SHALL load the existing secret keys from the `settings` table and use them for JWT verification and signing

#### Scenario: Previously issued tokens remain valid after restart
- **WHEN** a user holds a valid JWT access token or refresh token issued before a server restart
- **THEN** the token SHALL still be accepted by the server after restart (assuming the token has not expired)

### Requirement: Environment variable takes precedence over database
The system SHALL use `JWT_SECRET` and `JWT_REFRESH_SECRET` environment variables when they are explicitly set, overriding any values stored in the database.

#### Scenario: Environment variable overrides database key
- **WHEN** both `JWT_SECRET` environment variable and a persisted key in the `settings` table exist
- **THEN** the system SHALL use the environment variable value for JWT signing and verification

#### Scenario: Changing environment variable invalidates old tokens
- **WHEN** an administrator updates the `JWT_SECRET` environment variable and restarts the server
- **THEN** all tokens signed with the previous key SHALL be rejected (expected behavior, consistent with manual key rotation)

### Requirement: Settings table schema
The system SHALL maintain a `settings` table in the `auth.db` SQLite database with key-value structure to store persistent configuration.

#### Scenario: Settings table created on initialization
- **WHEN** `init_db()` is called during server startup
- **THEN** a `settings` table SHALL be created with `key TEXT PRIMARY KEY` and `value TEXT NOT NULL` columns if it does not already exist

#### Scenario: Key-value pair stored and retrieved
- **WHEN** a secret key is saved to the `settings` table with key `jwt_secret`
- **THEN** the same value SHALL be retrieved when querying by that key
