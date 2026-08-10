## Context

`verify_kb_access` has an `allowed_kbs` branch, but users loaded from PostgreSQL never contain that field.  The result is an incomplete scope model: owner and super-admin access work, while an explicit cross-owner grant cannot survive authentication or be administered.  The database has a migration runner and the production history is being baselined through migration 027 before later additive migrations are applied.

## Goals / Non-Goals

**Goals:**

- Persist user-to-KB grants independently from KB metadata and user roles.
- Project active grants into every authenticated user representation used by the KB access guard and KB list.
- Let `users:write` administrators replace a user's grant set atomically, with target existence validation and audit logging.
- Keep role capability and resource scope separate, including immediate session invalidation after a grant change.

**Non-Goals:**

- Do not give a role implicit access to additional KBs, create department hierarchies, or change KB ownership.
- Do not create per-grant read/write privilege levels; existing `kb:read` and `kb:write` remain the action gate.
- Do not rewrite old task snapshots, ingestion defaults, or platform settings.

## Decisions

### 1. Use a normalized grant table

Add `user_kb_access_grants(user_id, kb_name, granted_by, created_at)` with a composite primary key and an index by KB.  A table is selected over `users.allowed_kbs JSONB` because it can reference the existing user, supports atomic validation and audit trails, avoids scanning JSON for KB lists, and does not couple account identity to a mutable list.  No existing user receives a grant during migration; owners and super-admins preserve their current paths.

### 2. Replace the complete grant set atomically through the existing admin user API

Extend the admin user representation and `PUT /api/admin/users/{id}` with an optional `allowed_kbs` list.  When present, the repository locks the target user, validates that every KB exists, replaces only that user's grants transactionally, increments `session_generation`, and returns a sanitized list.  Separate grant endpoints were rejected because one update payload keeps account administration coherent and lets an empty list expressly revoke all grants.

### 3. Resolve access from role capability plus scope

After authentication, the repository returns `allowed_kbs` from the grant table.  `verify_kb_access` and `list_kbs` accept a KB when the caller is super-admin, its owner, or has an active grant.  The caller must still pass the endpoint's `kb:read` or `kb:write` guard, so a student grant enables read-only paths while an assistant grant enables writes within the same KB.  A `dept_admin` remains limited to owner-or-granted scope.

### 4. Present grants only to user administrators

The administrator user editor fetches the platform-visible KB catalog and displays grant selection only to users with `users:write`.  It submits names through the existing update API and refreshes the edited user on success.  The normal KB pages need no grant-management controls; their existing capability gates determine upload and ingestion-settings visibility after scope resolution.

## Risks / Trade-offs

- [An administrator revokes their own only grant] -> This is allowed because it does not affect global administrator quorum; subsequent requests lose KB scope through session invalidation.
- [A granted KB is deleted] -> KB deletion removes grants with a database foreign-key-style cleanup or repository cleanup in the same transaction; no dangling grant produces access.
- [Old issued tokens contain stale scopes] -> `session_generation` increments on grant mutation and the current validation path rejects the old session.
- [Concurrent admin edits overwrite grants] -> Replacement occurs under the target-user transaction lock; the latest completed update is the single committed grant set.

## Migration Plan

1. Apply the additive grant-table migration only through the reviewed migration runner after the approved 027 baseline and post-baseline migrations complete.
2. Deploy the repository, auth projection, dependency/list, API, and frontend changes together.
3. Verify owner access, grant-only read access, grant-only write access by an eligible role, revocation, and forbidden cross-owner requests with real PostgreSQL sessions.
4. Roll back application code if needed; grant rows are additive and can remain inert.  Revoking grants is the forward recovery path.  Database rollback is restoration from the verified backup, not destructive down migration.

## Open Questions

- None.  A grant denotes KB scope only; existing role permissions govern allowed actions.
