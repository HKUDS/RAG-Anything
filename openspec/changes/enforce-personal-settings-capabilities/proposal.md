## Why

Personal settings currently expose the same model and task controls to every
authenticated user, even when their role cannot use the corresponding
capability. Hiding controls alone would leave direct API writes and previously
stored overrides effective after a permission downgrade.

## What Changes

- Project personal-settings sections from live permissions: `kb:write` enables
  ingestion, retrieval, and runtime overrides; `agent:write` enables model
  overrides; appearance, account, and password controls remain available.
- Return the permitted section list and only permitted settings data/options
  from the existing personal-settings APIs; reject writes to denied sections.
- Protect the legacy personal VLM preference endpoints with the same model
  capability and remove the frontend fallback that fetches the generic catalog
  for users without model access.
- Resolve only permitted stored overrides for newly created agent requests and
  upload task snapshots. Existing durable snapshots remain unchanged.
- Update the preferences navigation, mounted sections, hash recovery, and route
  copy to match the current capability set.

## Capabilities

### New Capabilities

- `frontend-permission-gating`: apply capability-based visibility and inert
  behavior to the personal-settings surface.

### Modified Capabilities

- `personal-settings-center`: render only personal-setting sections available
  to the authenticated user's live permissions.
- `user-settings-resolution`: project settings/options by permitted section and
  ignore denied stored overrides when resolving new work.
- `rbac-authorization`: enforce the personal-settings section capability
  boundary at the API layer.

## Impact

Affected areas are the personal settings and vision routers, settings
resolution service, agent and upload snapshot boundaries, preferences page,
route metadata, and focused Python/Node tests. Existing API paths gain
capability-filtered response content and 403 behavior for denied writes; no
role definitions, permission constants, database schema, migration, or generic
model-profile catalog contract changes.
