## MODIFIED Requirements

### Requirement: Authorization decisions use RBAC role permissions exclusively

The system SHALL NOT use a deprecated `is_admin` boolean column as an authorization shortcut. All access control decisions SHALL go through `has_permission(user_id, permission)` which checks the user's role permissions.

#### Scenario: Admin user passes permission check through role
- **WHEN** an admin-role user accesses an endpoint protected by `require_permission(Permission.USERS_READ)`
- **THEN** the access SHALL be granted because the admin role's permissions include `users:read`

#### Scenario: Non-admin with is_admin=1 column is denied
- **WHEN** a user has `is_admin=1` in the deprecated column but `role_id` points to the viewer role
- **THEN** `get_current_user()` SHALL return `is_admin: false` (derived from role)
- **AND** protected endpoints SHALL enforce role-based permission checks

### Requirement: role_id updates are not silently dropped

The `update_user()` function SHALL accept `role_id` in its `allowed_fields` set, allowing role changes to persist to the database.

#### Scenario: Admin changes a user's role via API
- **WHEN** `PUT /admin/users/{user_id}` is called with `{"role_id": 3}` (viewer)
- **THEN** the user's `role_id` SHALL be updated to 3 in the database

#### Scenario: Rejected security-sensitive fields are logged
- **WHEN** `update_user()` receives fields like `is_admin`, `password_hash`, `failed_login_attempts`
- **THEN** these fields SHALL be rejected
- **AND** a WARNING log SHALL be emitted listing the rejected fields

### Requirement: JWT tokens do not carry is_admin authority claim

JWT access and refresh tokens SHALL carry only identity claims (`user_id`, `username`), not authority claims (`is_admin`). Authority SHALL be derived server-side from the RBAC system on every request.

#### Scenario: Access token payload does not contain is_admin
- **WHEN** an access token is issued
- **THEN** the JWT payload SHALL NOT contain an `is_admin` field

#### Scenario: Refresh token payload does not contain is_admin
- **WHEN** a refresh token is issued
- **THEN** the JWT payload SHALL NOT contain an `is_admin` field
