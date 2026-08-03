## 1. Permission policy and routing

- [x] 1.1 Add and test `permissionUiPolicy` capability mapping based on `hasPermission()` without role-name branching.
- [x] 1.2 Update route recovery to choose the first permitted destination across knowledge, agents, AutoRepair, workflow, monitor, platform, admin, and personal settings without rendering a 403 permission code; add `kb:read` to root/detail/chunks routes and `autorepair:write` to the AutoRepair agent route.
- [x] 1.3 Make App route subtitles, navigation descriptions, and cockpit statistics reflect read/use versus write/manage capabilities while preserving `globalStatsCache`, lazy loading, and existing navigation-performance changes.

## 2. Knowledge and agent pages

- [x] 2.1 Remove unavailable create/edit/delete controls and permission banners from `AgentsPage`; keep conversation access and teacher-specific delete gating.
- [x] 2.2 Remove knowledge directory read-only messaging and hide create/delete/empty-state CTAs according to `kb:write` and `kb:delete`.
- [x] 2.3 Update `KnowledgeDetailPage` and `DocumentChunksPage` to hide write controls, graph edits, vision writes, and read-only notices; use neutral empty and object-403 copy.

## 3. Workflow, monitoring, and platform views

- [x] 3.1 Make workflow toolbar, palette, canvas, and node configuration genuinely read-only when `workflow:write` is absent: all mutation callbacks, Ctrl+S/Enter/delete-key paths, React Flow drag/connect/delete flags, and NodeConfigPanel upload are silent no-ops or unmounted, with no permission toasts.
- [x] 3.2 Hide monitor cache-maintenance controls for users without `settings:write` while retaining read-only status data.
- [x] 3.3 Render platform policy as static read-only values for users without `settings:write`; retain only deployment-level read-only messaging.

## 4. AutoRepair capability boundaries

- [x] 4.1 Normalize AutoRepair KB selection state and remove fabricated fallback KBs; clear stale storage, handle pending/empty/403/network races, and skip dashboard, graph, case, QA, diagnosis, and code-parse requests without a confirmed KB.
- [x] 4.2 Fix `AutoRepairKBSelector` selected-value props and gate KB creation/upload controls by `kb:write`.
- [x] 4.3 Hide AutoRepair agent navigation, dashboard shortcuts/import guidance, QA, code parsing, diagnosis, and case mutation controls without `autorepair:write`; guard keyboard and shortcut paths.

## 5. Regression coverage

- [x] 5.1 Add pure unit tests for five-role capability visibility, full denied-route recovery order, route copy/statistics, and neutral object-403 behavior.
- [x] 5.2 Add AutoRepair KB normalization/request-gating tests for first render, list success, empty/403/network failure, stale in-flight cancellation, and every scoped request; add source contracts preventing ordinary permission banners/raw codes, permission toasts, and disabled unauthorized write controls from returning (allow only admin/audit details, deployment read-only state, and real network/service errors).
- [x] 5.3 Run focused backend RBAC regressions, frontend unit tests, Vite build, `git diff --check`, and available 1440/390 viewport plus keyboard smoke checks covering Enter/Ctrl+S/shortcut/write-request absence; record environment limitations when browser automation is unavailable.

## 6. Project closeout

- [x] 6.1 Update `PROJECT_SUMMARY.md` current facts and append the implementation/verification record without modifying unrelated dirty work.
- [x] 6.2 Re-run OpenSpec validation and confirm no API, migration, or backend permission changes were introduced.
