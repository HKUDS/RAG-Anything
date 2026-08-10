## Why

The current knowledge-base collaboration model stores only an untyped scope
grant through the administrator user editor.  It cannot distinguish read-only
members from content operators, lets an unrelated user-management route bypass
object-level rules, and provides no safe knowledge-base-page workflow for a
user to rename a KB or manage its members.

## What Changes

- Add knowledge-base member management with explicit `read` and `operate`
  access levels, atomic change auditing, and immediate invalidation of the
  affected member's sessions.
- Add the `kb:manage` capability and enforce the five-role object-level
  management matrix without introducing a department data model.
- Add a display-name-only KB metadata update guarded by an optimistic version;
  internal KB names, workspaces, indexes, documents, and grant identities do
  not change.
- Add KB-scoped member, constrained candidate-search, grant-upsert, grant-
  revoke, and metadata APIs; return backend-derived rename/member capabilities
  from the KB list.
- **BREAKING** Remove `allowed_kbs` mutation from the administrator user-update
  route and its frontend editor; clients must use KB-scoped member APIs.
- Add the capability-gated knowledge-base card menu and SideDrawer workflows
  for basic information and members on desktop and mobile.

## Capabilities

### New Capabilities
- `knowledge-base-member-management`: manages per-member KB read/operate
  scope, candidate eligibility, audit records, session invalidation, and the
  member-management experience.
- `knowledge-base-display-name-management`: updates a KB's presentation name
  without changing its stable internal identity or dependent data.

### Modified Capabilities
- `kb-access-control`: distinguish read and operate grants, enforce object
  scope for every KB read/write route, and surface management capabilities.
- `admin-user-crud`: retire the legacy `allowed_kbs` batch-edit contract so it
  cannot bypass KB-scoped authorization.

## Impact

Affected areas include PostgreSQL migrations and the migration manifest, role
permissions, authentication/grant repositories and audits, FastAPI KB and
admin routes, all KB-scoped access guards, KB list serialization, the React
knowledge-base page/API client/user editor, focused backend/frontend tests,
and the project summary.  Existing internal KB identifiers, workspaces,
indexes, documents, task snapshots, and global user roles remain unchanged.
