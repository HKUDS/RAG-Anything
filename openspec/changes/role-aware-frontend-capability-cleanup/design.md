## Context

The completed RBAC hardening change added permission checks to the frontend, but its UI contract still permits disabled controls and page-level read-only notices. Low-permission users need a useful read view with only executable actions mounted. The current worktree also contains an uncommitted navigation-performance change, so this change must be integrated incrementally.

The backend remains the authorization source of truth. `require_permission()` and object-level ownership checks continue to return 401/403. The frontend receives the live permission set through `AuthContext.hasPermission()` and only shapes the visible experience around it.

## Goals / Non-Goals

Goals:

- Provide one permission-to-capability policy used by route metadata and page controls.
- Render only operations the current user can perform while retaining useful read-only views.
- Remove routine permission/read-only notices and raw permission identifiers from ordinary business pages.
- Make read-only workflow canvases and AutoRepair pages unable to trigger writes through clicks, keyboard input, or shortcuts.
- Prevent stale or fabricated AutoRepair KB selections from causing unauthorized scoped requests.
- Preserve current performance changes, server-side authorization, admin permission/audit details, and deployment-state warnings.

Non-goals:

- No changes to backend permission constants, role definitions, API payloads, database schema, or migrations.
- No granting of `autorepair:write` to read-only roles.
- No separate page tree per role; behavior is derived from the live permission set.

## Decisions

### 1. Centralize UI capabilities, not authorization

Add a pure `createPermissionUiPolicy(hasPermission)` helper under `frontend/src/utils/`. Pages consume capability booleans such as `canCreateAgent`, `canEditWorkflow`, and `canUseAutoRepairAgent`. The helper never authorizes API calls and never branches on role names.

### 2. Hide unavailable controls instead of disabled controls

Conditional rendering is the default for create/edit/delete buttons, inputs, tabs, quick actions, and empty-state CTAs. Handlers retain silent early returns as defense in depth. Read-only pages show data and neutral empty states; they do not explain missing permissions.

### 3. Recover denied routes without exposing permission internals

`ProtectedRoute` uses a route-recovery helper. It chooses the first permitted destination in this order, skipping the current path to avoid loops:

1. `kb:read` -> `/knowledge`
2. `agent:read` -> `/agents`
3. `autorepair:read` -> `/autorepair`
4. `workflow:read` -> `/workflow`
5. `monitor:read` -> `/monitor`
6. `settings:read` -> `/admin/platform`
7. `users:read` -> `/admin/users`
8. `audit:read` -> `/admin/audit-logs`
9. `/preferences`

The root route and every `/knowledge/*` detail route explicitly require `kb:read`. A denied route renders no 403 panel and no permission code.

### 4. Treat AutoRepair KB identity as confirmed state

`useAutoRepairKB` starts with no selected KB until `/autorepair/kb-list` returns an accessible list. Empty, failed, or forbidden responses clear stale local storage and leave the active KB unset. Dashboard, graph summary/nodes/edges/lineage, case stats/search, QA, diagnosis, and code-parse requests are skipped without a confirmed `arKb`. A request generation guard prevents an older list response from committing over a newer one. Selectors and callers use the same `arKb` prop name.

### 5. Make read-only workflow interaction truly inert

When `workflow:write` is absent, mutation toolbar actions, node palette/configuration, and NodeConfigPanel file upload are unmounted. `wrappedOnNodesChange`, `wrappedOnEdgesChange`, `onConnect`, `onDropNode`, `handleNodeUpdate`, and `handleAutoLayout` are silent no-ops. React Flow disables drag, connect, delete-key, and mutation selection behavior. Ctrl+S, Enter, and equivalent handlers are silent no-ops. Loading, inspecting, zooming, and other reads remain available.

### 6. Preserve the dirty performance change

Patch only permission-related branches. Preserve `globalStatsCache`, `knowledgeDetail*`, lazy D3, polling, skeleton, and navigation prefetch behavior. Review diffs in `App.jsx`, `AgentsPage.jsx`, `KnowledgePage.jsx`, `KnowledgeDetailPage.jsx`, and `MonitorPage.jsx`; do not whole-file rewrite or format those shared hotspots.

## Risks / Trade-offs

- Hiding controls can reduce discoverability. Keep readable page subtitles and visible read data; do not show unavailable actions as disabled controls.
- Custom users may have neither `kb:read` nor `agent:read`. Route recovery continues through the complete list and ends at personal settings.
- A stale in-flight callback could invoke a write handler. Keep silent permission guards and test direct handler, keyboard, and shortcut paths.
