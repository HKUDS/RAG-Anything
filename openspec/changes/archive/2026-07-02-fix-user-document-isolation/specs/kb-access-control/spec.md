## ADDED Requirements

### Requirement: KB access enforces strict ownership isolation
All knowledge-base-scoped API endpoints SHALL enforce that non-admin users can only access knowledge bases they own (`owner_id == current_user["id"]`). Any attempt by a non-admin user to access another user's knowledge base MUST result in the request being redirected to the user's own knowledge base, or receiving a 403 Forbidden error. Under no circumstances SHALL a non-admin user receive data from another user's knowledge base.

#### Scenario: Non-admin user with own KB attempts cross-user access
- **WHEN** a non-admin user who already owns at least one knowledge base sends a request targeting another user's knowledge base (e.g., `GET /api/knowledge/documents?kb=other_user_kb`)
- **THEN** the system SHALL silently redirect the request to the requesting user's own knowledge base instead, returning data from their own KB

#### Scenario: Non-admin new user with zero KBs attempts cross-user access
- **WHEN** a newly registered non-admin user who owns zero knowledge bases sends a request targeting another user's knowledge base
- **THEN** the system SHALL auto-create a personal knowledge base for the user and redirect the request to it, returning empty data from the newly created KB

#### Scenario: Admin user accesses any KB
- **WHEN** an admin user sends a request targeting any knowledge base
- **THEN** the system SHALL allow access and return data from the requested knowledge base

#### Scenario: User accesses their own KB
- **WHEN** a user sends a request targeting a knowledge base where `owner_id == current_user["id"]`
- **THEN** the system SHALL allow access and return data from the requested knowledge base

### Requirement: KB list endpoint filters by ownership
The `/api/kb/list` endpoint SHALL return only knowledge bases owned by the requesting user for non-admin users. Admin users SHALL receive the full list of all knowledge bases.

#### Scenario: Non-admin user lists KBs
- **WHEN** a non-admin user requests `GET /api/kb/list`
- **THEN** the response SHALL contain only knowledge bases where `owner_id` matches the current user's ID

#### Scenario: New user with zero KBs lists KBs
- **WHEN** a non-admin user who owns zero knowledge bases requests `GET /api/kb/list`
- **THEN** the system SHALL auto-create a personal knowledge base, and the response SHALL contain exactly that one KB with `active: true`

### Requirement: Frontend defers KB data loading until ownership is confirmed
The knowledge base page frontend SHALL NOT request any knowledge-base-scoped data (documents, stats, entities, graph) until the user's KB list has been successfully fetched and the active KB has been confirmed to belong to the user.

#### Scenario: KnowledgePage mounts for the first time
- **WHEN** the KnowledgePage component mounts
- **THEN** it SHALL first call `/api/kb/list` and await the response before making any KB-scoped data calls (documents, stats, entities, graph)

#### Scenario: KB data loading uses confirmed active KB
- **WHEN** `loadKBData()` executes
- **THEN** the `activeKB` value used SHALL have been derived from the `/api/kb/list` response and confirmed present in the user's KB list, never from a hardcoded default

### Requirement: Module-level KB state validates before use
The frontend module-level `currentKB` state SHALL validate that the KB name is non-empty and exists in the user's KB list before appending it to any API request URL. Requests with an unconfirmed or empty KB name SHALL NOT be dispatched.

#### Scenario: API request with uninitialized KB state
- **WHEN** an API call is made before `currentKB` has been set to a confirmed user-owned KB
- **THEN** the request SHALL be skipped or deferred, not dispatched with a hardcoded or stale KB name
