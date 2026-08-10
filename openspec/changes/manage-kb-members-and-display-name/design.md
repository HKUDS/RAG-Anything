## Context

`kb_access_grants` currently projects a KB name into `allowed_kbs`, which is
scope-only and is edited by the unrelated administrator user-update route.
The system has five global roles but no object-level distinction between a
reader and a non-owner who can maintain a KB.  Internal KB `name` is a stable
key for workspace paths, task/document rows, indexes, and grants, while the
metadata repository already exposes a separate presentation label.

## Goals / Non-Goals

**Goals:**

- Preserve five-role global RBAC while adding explicit KB `read`/`operate`
  scope and a fail-closed object-level management rule.
- Offer concurrency-safe display-name editing and KB-scoped membership APIs
  with audit records, target session invalidation, and constrained discovery.
- Apply the same operation guard consistently to every content mutation route.
- Provide a capability-driven, keyboard-accessible SideDrawer interface.

**Non-Goals:**

- Do not rename internal KB names or migrate workspaces, indexes, documents,
  task snapshots, or ownership.
- Do not add departments, classes, inheritance, or member-specific roles.
- Do not let grants grant `kb:write`, `kb:manage`, or another global ability.

## Decisions

### 1. Store an explicit access level on the normalized grant

Add a non-null `access_level` constrained to `read` or `operate` to
`kb_access_grants`.  Upgrade existing rows using the target role's
`kb:write` capability, preserving the prior teacher/assistant write behavior
while treating all other users as readers.  A normalized row continues to
support foreign keys, atomic locking, and audit attribution; JSON on `users`
would make those properties weaker.

### 2. Centralize scope, operation, and management decisions

The dependency layer exposes three predicates: read scope (owner,
super-admin, read/operate grant), operation scope (owner, super-admin, or
operate grant), and management scope (super-admin; dept_admin in its read
scope; teacher only as owner).  Endpoint permissions remain mandatory:
read requires `kb:read`, operation requires `kb:write`, and management
requires `kb:manage`.  This separates resource scope from global roles and
prevents UI visibility from becoming authorization.

### 3. Make member changes KB-scoped and serializable

Member list/search/upsert/revoke APIs authorize the caller against the
current KB, lock the relevant KB/grant/target rows in one transaction, validate
role rank and target state, write an audit event, and increment the target
`session_generation`.  Candidate search requires two characters and pages
results so an owner cannot enumerate the user directory.  Owners and
super-admins do not receive redundant grants; `operate` requires that the
target role already owns `kb:write`.

The legacy `allowed_kbs` field is rejected by the admin user-update API,
instead of preserving a second mutation path.

### 4. Update only display metadata with an optimistic version

`PATCH /api/kb/{name}/metadata` changes only `kb_metadata.display_name` after
comparing an `expected_updated_at` value to the current metadata timestamp.
The update returns 409 on a mismatch and audits success.  This keeps physical
identity immutable while allowing users to resolve concurrent edits.

### 5. Make the frontend consume backend capabilities

The KB list serializes `capabilities.rename` and
`capabilities.manage_members`.  The card menu is rendered only from those
values.  A reusable SideDrawer contains independent basic-information and
members actions, preserves a failed draft, marks the owner immutable, and
invalidates list/detail state after mutations.  The drawer is full-width on
small screens and its primary controls have a 44px target.

## Risks / Trade-offs

- [A missed content mutation keeps the old scope-only behavior] -> Enumerate
  and replace all KB write dependencies, backed by source-contract tests.
- [Backfill incorrectly changes existing collaborators] -> Select levels from
  the role-permission relation and verify fresh, upgrade, repeat, and failure
  migration paths against disposable PostgreSQL.
- [Concurrent member edits overwrite each other] -> Lock the grant row and
  serialize the change; expose current state after each response.
- [Session invalidation leaves a stale browser view] -> Increment the target
  generation transactionally and test old-token rejection plus refreshed list
  visibility.
- [Role names drift from capability definitions] -> Determine `operate`
  eligibility from `kb:write`, never a hard-coded role allow-list.

## Migration Plan

1. Take the required verified PostgreSQL backup, then apply the additive
   manifest migration through the migration runner.
2. Deploy the repository/dependency/router changes with the migration before
   enabling the frontend editor.
3. Verify all five roles against list/read/write/manage API paths and confirm
   existing internal KB identity/data remain unchanged after a display-name
   change.
4. Roll application code back if necessary; forward recovery revokes or
   downgrades grants.  Database rollback is restoration from the backup, not
   a destructive down migration.

## Open Questions

- None.  The approved matrix fixes `dept_admin` at own-or-granted scope and
  treats teacher management as owner-only.
