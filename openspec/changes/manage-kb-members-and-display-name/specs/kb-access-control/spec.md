## MODIFIED Requirements

### Requirement: KB access enforces strict ownership isolation
All knowledge-base-scoped API endpoints SHALL enforce that a caller can read a
KB only when the caller is a super-admin, owns the KB
(`owner_id == current_user["id"]`), or has an explicit `read` or `operate`
grant.  Every content mutation SHALL additionally require owner/super-admin
scope or an `operate` grant, plus the endpoint's `kb:write` permission.  Any
other request MUST return 403 Forbidden and MUST NOT return cross-owner KB
data.  `dept_admin` SHALL receive no implicit global scope.

#### Scenario: Granted reader accesses another user's KB
- **WHEN** a user with `kb:read` and an explicit read grant sends a request targeting another user's KB
- **THEN** the system SHALL allow the KB-scoped read request

#### Scenario: Granted reader cannot write another user's KB
- **WHEN** a user with a read grant sends a KB write request targeting another user's KB
- **THEN** the system SHALL return 403 because the grant does not supply operate scope

#### Scenario: Granted operator requires global write permission
- **WHEN** a user with an operate grant but without `kb:write` sends a KB write request
- **THEN** the system SHALL return 403 because the grant does not supply global capability

#### Scenario: Ungranted non-owner accesses another user's KB
- **WHEN** a non-owner without an explicit grant sends a request targeting another user's KB
- **THEN** the system SHALL return 403 without returning data from that KB

#### Scenario: Owner and super-admin access remain available
- **WHEN** the KB owner or a super-admin targets an existing KB
- **THEN** the system SHALL allow access subject to the endpoint's existing permission requirements

### Requirement: KB list endpoint filters by ownership
The `/api/kb/list` endpoint SHALL return all KBs to a super-admin and, for
every other user, exactly the union of KBs the user owns and KBs covered by an
explicit grant.  Each item SHALL include backend-derived `rename` and
`manage_members` capabilities.  It SHALL NOT return unrelated KBs.

#### Scenario: Non-owner lists a granted KB
- **WHEN** a non-super-admin requests `GET /api/kb/list` after receiving a grant to another user's KB
- **THEN** the response SHALL include the granted KB and the user's owned KBs

#### Scenario: Revoked KB disappears from the list
- **WHEN** an administrator revokes a non-owner's access to a KB
- **THEN** the next authenticated `GET /api/kb/list` response SHALL not include that KB unless the user owns it
