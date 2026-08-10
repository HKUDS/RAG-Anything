## MODIFIED Requirements

### Requirement: Admin can update user
The system SHALL provide `PUT /api/admin/users/{id}` for role and account
state changes.  Administrators MUST NOT cancel their own administrator role.
The request MUST reject the legacy `allowed_kbs` field and direct callers to
KB member-management endpoints; user updates SHALL NOT mutate KB grants.

#### Scenario: Change user role
- **WHEN** an administrator calls `PUT /api/admin/users/{id}` with an allowed role update
- **THEN** the system SHALL update the user's role and return 200

#### Scenario: Admin cannot demote themselves
- **WHEN** an administrator attempts to modify their own `role_id` to a non-administrator role
- **THEN** the system SHALL return 403 Forbidden with an explanatory error

#### Scenario: Disable user account
- **WHEN** an administrator calls `PUT /api/admin/users/{id}` with `is_active=false`
- **THEN** the system SHALL disable the account and later login requests SHALL return 403

#### Scenario: Legacy KB grants are rejected
- **WHEN** an administrator sends `allowed_kbs` in a user update request
- **THEN** the system SHALL return a validation error and leave KB grants unchanged
