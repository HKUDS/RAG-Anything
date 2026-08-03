## Why

Ordinary business pages already consult RBAC, but low-permission users still see disabled controls, read-only banners, permission strings, and AutoRepair shortcuts that cannot work. This makes the UI look broken and can trigger misleading scoped 403 states when an AutoRepair KB is empty or inaccessible.

## What Changes

- Use live `hasPermission()` capability mapping so unavailable write buttons, inputs, tabs, shortcuts, and empty-state CTAs are not mounted.
- Keep read-authorized pages useful while removing routine permission/read-only disclosures and raw permission identifiers from ordinary business pages.
- Recover denied direct routes silently using a complete read-route priority, with `kb:read` on all knowledge routes and `autorepair:write` on the AutoRepair agent route.
- Make read-only workflow canvases inert, including callbacks, React Flow flags, keyboard shortcuts, node configuration, and uploads.
- Fix AutoRepair KB confirmation state so empty, failed, or forbidden lists clear stale selections and no scoped dashboard, graph, case, QA, diagnosis, or code request is sent.
- Keep user-management and audit permission details, deployment read-only status, real service errors, backend RBAC, APIs, migrations, and the dirty navigation-performance change unchanged.

## Capabilities

### New Capabilities

- `role-aware-frontend-capability`: shared capability mapping, visible-entry policy, inert read-only surfaces, and denied-route recovery.

### Modified Capabilities

- `kb-access-control`: knowledge routes require `kb:read`; AutoRepair KB-scoped requests require a confirmed selected KB and never use a fabricated fallback.
- `frontend-permission-gating`: supersedes the completed change's allowance for disabled controls and routine read-only banners; unauthorized write controls are unmounted and read-only mutation callbacks are inert.

## Impact

Primary impact is `frontend/src/App.jsx`, route protection, the shared permission policy, agents/knowledge/workflow/monitor/platform pages, AutoRepair pages and hook, and focused frontend unit/source-contract tests. No backend permission matrix, API contract, database migration, or server-side authorization changes are in scope.
