## Why

Page switches feel slow: after navigating, content takes roughly 500ms to
appear while pages briefly show misleading "empty" states (e.g. "这里还没有智能体",
"暂无实体数据"). Root causes: pages fetch data only after mount, `AgentsPage`
lacks a loading gate, clicking a knowledge base card blocks navigation on a
prefetch (up to 6s), every route change refetches global stats, and the entry
bundle carries ~112KB of framer-motion plus a render-blocking Google Fonts
request.

## What Changes

- Knowledge base card clicks navigate immediately; detail prefetch continues in
  the background and the detail page renders cached data or skeletons first.
- The knowledge detail page loads only core data (documents/stats via prefetch,
  upload tasks) on mount; entities/graph load on demand when the graph tab is
  opened, with loading skeletons instead of empty-state flashes, and d3 loads
  lazily only when the graph tab first needs it.
- The detail page polling becomes visibility- and task-aware: a 15s loop that
  refreshes the upload-task snapshot inside the loop as the gate, polls core
  data only while non-terminal tasks exist, performs one final refresh when
  tasks turn terminal, stops while the tab is hidden, and refreshes graph data
  only while the graph tab is active.
- Global stats requests get a 30s TTL cache keyed by the current KB (in-flight
  dedupe, no caching of the empty early return, invalidation on auth
  generation change), are restricted to knowledge routes, and are skipped while
  the tab is hidden.
- Empty-state gating is audited and unified (loading = skeleton, empty = only
  after load completes): `AgentsPage` gains a loading gate, `MonitorPage` and
  `AgentChatPage` empty states get loading gates, and the KB list shows a
  skeleton while loading.
- Lazy route chunks are hover-prefetched from the sidebar/topbar navigation,
  guarded by `navigator.connection.saveData`.
- Fonts are self-hosted (`@fontsource/inter`, `@fontsource/jetbrains-mono`),
  removing the Google Fonts render-blocking link and preconnects.
- framer-motion is removed from the entry critical path (App-level toast/menu/
  loader use CSS transitions); pages keep using it inside their lazy chunks.
- Vite manual chunks are refined so d3 loads only with the graph tab; nginx
  caches hashed `/assets/` immutably (repeating security headers inside new
  locations) and disables caching for `index.html`; the app renders before
  `synchronizeSystemDataEpoch()` completes and reloads immediately if the epoch
  changed during background sync.

## Capabilities

### New Capabilities

- `frontend-navigation-performance`: cached-first navigation, loading-skeleton
  vs empty-state contract, on-demand graph/entity loading, stats TTL caching,
  and route-chunk hover prefetch.

### Modified Capabilities

- `frontend-smart-polling`: knowledge detail polling becomes visibility- and
  task-aware (task snapshot refreshed inside the loop, 15s idle interval,
  final refresh on terminal transition) instead of an unconditional 8s force
  poll.

## Impact

Frontend: `App.jsx`, `KnowledgePage.jsx`, `KnowledgeDetailPage.jsx`,
`AgentsPage.jsx`, `MonitorPage.jsx`, `AgentChatPage.jsx`, `utils/api.js`,
`utils/lazyD3.js` (new), `main.jsx`, `index.html`, `index.css`,
`vite.config.js`, `package.json`. Deployment: `nginx.conf`. New frontend
dependencies: `@fontsource/inter`, `@fontsource/jetbrains-mono`. No backend
API, RBAC, or schema changes.

## Acceptance

- Clean production build is generated as the before-baseline (dist is
  git-ignored); the key chain (entry + react/router/icons vendors + css) raw
  size drops ≥20% after the change; `dist/index.html` no longer references
  `fonts.googleapis.com`.
- `npm run test:unit` stays green (81 existing tests) with new unit tests for
  stats TTL keying, polling gate decisions, and terminal-transition refresh.
