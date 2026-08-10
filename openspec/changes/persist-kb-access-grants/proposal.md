## Why

The access guard already recognizes `allowed_kbs`, but PostgreSQL user records do not persist it.  This leaves cross-owner collaboration unavailable after restart and makes the five-role knowledge-base scope inconsistent with the approved role matrix.

## What Changes

- Add a durable, normalized knowledge-base access-grant relation for users and backfill no implicit cross-owner grants.
- Let authorized user administrators grant and revoke a user's access to named knowledge bases through the existing user-management surface and API.
- Make authentication projection, knowledge-base listing, and every KB-scoped access guard consistently use persisted grants in addition to ownership and existing super-admin access.
- Preserve the existing role capability model: a grant supplies scope only; `kb:read` and `kb:write` still determine which actions are allowed, and `dept_admin` receives no automatic global scope.

## Capabilities

### New Capabilities
- `knowledge-base-access-grants`: durable, auditable per-user grants that project into authenticated KB scope.

### Modified Capabilities
- `kb-access-control`: allow an explicitly granted non-owner to access and list only their granted KBs, while preserving owner and super-admin behavior.
- `admin-user-crud`: allow authorized administrators to manage a user's KB access grants with validation and audit records.

## Impact

Affected areas include a new PostgreSQL migration, the authentication repository and token/session projection, KB list/access dependencies, administrator user APIs and UI, role-aware frontend tests, and PostgreSQL integration acceptance.  Existing KB ownership, ingestion defaults, platform policy ownership, and task snapshots are unchanged.
