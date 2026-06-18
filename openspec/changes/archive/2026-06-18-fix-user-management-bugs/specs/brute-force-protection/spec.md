## ADDED Requirements

### Requirement: Failed login attempts are recorded per user

The system SHALL increment the `failed_login_attempts` counter for a user when an incorrect password is submitted for that username.

#### Scenario: Failed login increments counter
- **WHEN** a login attempt is made with a valid username but incorrect password
- **THEN** the `failed_login_attempts` column for that user SHALL be incremented by 1 in the database

#### Scenario: Successful login resets counter
- **WHEN** a login attempt is made with a valid username and correct password
- **THEN** the `failed_login_attempts` column for that user SHALL be reset to 0

### Requirement: Account locks after exceeding maximum failed attempts

The system SHALL set `locked_until` to a future timestamp when `failed_login_attempts` exceeds `MAX_FAILED_ATTEMPTS` (default 5).

#### Scenario: Account locks after 5 consecutive failures
- **WHEN** a user has `failed_login_attempts = 5` and submits another incorrect password
- **THEN** `locked_until` SHALL be set to `now + LOCKOUT_DURATION_MINUTES` (default 15 minutes)

#### Scenario: Locked account login is rejected with error message
- **WHEN** a locked account attempts to login with correct credentials during the lockout period
- **THEN** the system SHALL return HTTP 403 with a lockout message

### Requirement: Locked accounts are blocked on authenticated requests

The system SHALL check account lock status in `get_current_user()` dependency and reject requests from locked accounts even if they hold a valid JWT.

#### Scenario: Authenticated request with locked account returns 403
- **WHEN** an authenticated request is made using a valid token from a locked account
- **THEN** the system SHALL return HTTP 403 with a lockout message

### Requirement: Lockout functions use user_id for lookups

All brute-force protection functions (`record_failed_login`, `reset_failed_logins`, `check_account_locked`) SHALL accept `user_id: int` and query by the `id` primary key column.

#### Scenario: Type mismatch does not cause silent bypass
- **WHEN** `check_account_locked` is called with a valid integer `user_id`
- **THEN** the function SHALL correctly query and return the lock status for that user
