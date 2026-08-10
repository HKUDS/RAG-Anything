## ADDED Requirements

### Requirement: KB member grants have explicit effective scope
The system SHALL store each non-owner KB member grant as `read` or `operate`.
Read scope SHALL permit a caller with `kb:read` to use KB read endpoints;
operate scope SHALL additionally permit a caller with `kb:write` to use KB
content mutation endpoints.  A grant SHALL NOT add any global permission or
member-management authority.

#### Scenario: Read member cannot mutate content
- **WHEN** a user with a `read` grant calls a KB content mutation endpoint
- **THEN** the system SHALL return 403 even when the user has `kb:write`

#### Scenario: Operate member has content scope
- **WHEN** a user with an `operate` grant and `kb:write` calls a KB content mutation endpoint
- **THEN** the system SHALL authorize that request subject to endpoint-specific validation

### Requirement: KB member management follows the five-role matrix
The system SHALL allow `super_admin` to manage all KBs, `dept_admin` to manage
only owned or explicitly granted KBs, and `teacher` to manage only owned KBs.
`assistant` and `student` SHALL not manage members.  A member grant SHALL NOT
confer management authority.

#### Scenario: Teacher cannot manage a granted KB
- **WHEN** a teacher with a read or operate grant targets a KB owned by another user
- **THEN** member-management endpoints SHALL return 403

#### Scenario: Granted department administrator manages a KB
- **WHEN** a dept_admin with explicit KB scope calls a member-management endpoint
- **THEN** the system SHALL authorize the request after `kb:manage` validation

### Requirement: Member mutation validates targets and invalidates sessions
The member APIs SHALL list members, search eligible candidates with a minimum
two-character query and pagination, upsert one member grant, and revoke one
member grant.  They SHALL reject missing, inactive, archived, higher-ranked,
owner, and super-admin targets; `operate` SHALL be rejected when the target
lacks `kb:write`.  Each committed grant mutation SHALL be atomic, audited, and
increment the target user's session generation.

#### Scenario: Revocation invalidates the target session
- **WHEN** an authorized manager revokes a member grant
- **THEN** the committed transaction SHALL audit the action and invalidate the target's existing sessions

#### Scenario: Candidate search avoids directory enumeration
- **WHEN** a manager searches candidates with fewer than two characters
- **THEN** the system SHALL reject the request without returning user records

### Requirement: Member UI is capability-gated and accessible
The KB card SHALL show its editor entry only when backend capabilities allow
rename or member management.  The member drawer SHALL show owner and effective
access, keep the owner non-removable, preserve unsaved edits on failed writes,
and provide keyboard-operable controls with a full-width mobile drawer and
44px minimum action targets.

#### Scenario: User without member capability sees no entry
- **WHEN** a KB list item reports `manage_members=false` and `rename=false`
- **THEN** the frontend SHALL not render a KB editor action for that item
