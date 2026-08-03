# Role-Aware Frontend Capability

## ADDED Requirements

### Requirement: Frontend operations follow live permission capabilities
The frontend SHALL derive operation visibility from the authenticated user's live permission set through `hasPermission()` and SHALL NOT hard-code role names for ordinary page behavior. A control that would issue a write-only request MUST NOT be mounted when its required permission is absent.

#### Scenario: Student opens the agent directory
- **WHEN** the user has `agent:read` but lacks `agent:write` and `agent:delete`
- **THEN** the page shows searchable agents and conversation links, but does not mount create, edit, delete, or create-first-agent controls

#### Scenario: Teacher lacks delete permissions
- **WHEN** the user has `agent:write` and `kb:write` but lacks `agent:delete` and `kb:delete`
- **THEN** create/edit and upload controls remain available, while agent and knowledge-base delete controls are absent

#### Scenario: Assistant maintains knowledge content
- **WHEN** the user has `kb:write` and `graph:write` but lacks `agent:write` and `autorepair:write`
- **THEN** knowledge upload/content and graph-edit controls are available, while agent-edit, AutoRepair-case-edit, QA, diagnosis, and workflow-write controls are absent

### Requirement: Read-only pages remain useful without permission disclosures
Pages SHALL retain read-authorized content and neutral empty states, but ordinary business pages MUST NOT show routine read-only banners, missing-permission explanations, raw permission identifiers, or disabled write controls. User management and audit-log permission details remain available to users authorized for those administrative pages.

#### Scenario: Student views an empty knowledge directory
- **WHEN** the student has `kb:read` but no `kb:write` or `kb:delete`
- **THEN** the empty state is neutral and contains no create CTA, permission code, or instruction to contact an administrator

#### Scenario: Department admin views platform policy
- **WHEN** the department admin has `settings:read` but lacks `settings:write`
- **THEN** policy values are readable as static content, editing inputs and save controls are absent, and no role-permission warning is shown

#### Scenario: Deployment is explicitly read-only
- **WHEN** the platform policy reports a deployment-level read-only state
- **THEN** the deployment-state warning remains visible even if the user is a super administrator

### Requirement: Read-only workflow and AutoRepair surfaces cannot issue writes
When a user lacks the permission required by a workflow or AutoRepair write endpoint, the frontend SHALL remove the corresponding mutation surface and SHALL prevent mouse, keyboard, shortcut, and local-canvas interactions from issuing that write request.

#### Scenario: Teacher opens a workflow with read permission only
- **WHEN** the teacher has `workflow:read` but lacks `workflow:write`
- **THEN** the user can load and inspect workflows, while palette, node editing, drag/connect/delete, save, run, new, and delete actions are unavailable

#### Scenario: Read-only workflow callbacks are inert
- **WHEN** `workflow:write` is absent
- **THEN** `wrappedOnNodesChange`, `wrappedOnEdgesChange`, `onConnect`, `onDropNode`, `handleNodeUpdate`, `handleAutoLayout`, delete-key handling, Ctrl+S, Enter, and node configuration upload return without changing local state or dispatching a write request

#### Scenario: Student opens the AutoRepair dashboard
- **WHEN** the student has `autorepair:read` but lacks `autorepair:write`
- **THEN** the dashboard and knowledge view remain available, while AutoRepair agent links, QA, code parsing, diagnosis, import scripts, and write shortcuts are absent

#### Scenario: AutoRepair has no confirmed knowledge base
- **WHEN** `/api/autorepair/kb-list` is pending, empty, forbidden, or failed
- **THEN** the first render and every dependent effect have no selected KB and issue no graph, QA, diagnosis, or code-parse request; stale local storage is cleared

### Requirement: Unauthorized direct routes recover without exposing permission internals
When an authenticated user directly opens a route for which they lack the required permission, the frontend SHALL navigate to the first permitted recovery destination and SHALL NOT render a 403 panel containing the required permission string.

#### Scenario: User directly opens a write-only AutoRepair route
- **WHEN** the user lacks `autorepair:write` and opens `/autorepair/agent`
- **THEN** the frontend replaces the route with `/autorepair` or another permitted recovery destination without showing a permission code

#### Scenario: User directly opens an inaccessible administrative route
- **WHEN** the user lacks the route's read permission
- **THEN** the frontend navigates away without rendering a technical authorization message

### Requirement: Capability statistics and copy match available actions
Route subtitles, navigation descriptions, and summary statistics SHALL describe what the current permission set can actually do, using read/use wording for read-only users and configuration/management wording only when the corresponding write capability exists.

#### Scenario: Student opens the agent directory
- **WHEN** the student can use agents but cannot edit them
- **THEN** route metadata and cockpit statistics describe browsing or using agents and do not claim that assistants, templates, or models are configurable
