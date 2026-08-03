## MODIFIED Requirements

### Requirement: Account updates are verified and audited without secrets
The system SHALL return non-secret user profile data from `GET /api/auth/me` without any email field, provide username update at `PUT /api/auth/me/profile` after current-password verification, and normalize the current-password verification behavior of `PUT /api/auth/me/password`. Successful updates SHALL preserve the session, refresh authentication context, and audit only non-secret result metadata.

#### Scenario: Profile update with correct password
- **WHEN** an authenticated user submits a valid new username and current password
- **THEN** the system persists the username, preserves login, and returns refreshed non-secret user data without any email field

#### Scenario: Incorrect password never enters audit data
- **WHEN** profile or password verification fails
- **THEN** the system rejects the request and audit data contains no supplied password value
