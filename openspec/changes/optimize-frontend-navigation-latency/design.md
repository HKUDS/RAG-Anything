## Context

The frontend is a React 18 + Vite SPA with route-level code splitting already in
place. Pages mount then fetch, so a route change shows an empty-state flash for
roughly 500ms until the first response renders. Clicking a knowledge base card
additionally blocks navigation on `prefetchKnowledgeDetail(..., timeoutMs: 6000)`.
The entry bundle carries framer-motion (~112KB) and a render-blocking Google
Fonts link. Production is served by nginx from hashed Vite assets with no cache
headers.

## Goals / Non-Goals

**Goals:**
- Content is visible immediately after navigation (cached-first) and loading is
  always a skeleton, never an empty-state flash.
- Knowledge detail initial requests drop to core data only; graph/entities load
  on demand with lazy d3.
- Polling is visibility- and task-aware instead of an unconditional 8s force
  poll, with no refresh gap when tasks turn terminal.
- First-load payload shrinks (framer-motion out of entry, self-hosted fonts,
  immutable nginx caching).

**Non-Goals:**
- No backend API, RBAC, or database changes; `/knowledge/stats` latency is
  mitigated on the client only.
- No dependency replacement of React/router; existing lazy chunk boundaries for
  pages remain.

## Decisions

1. **Click navigation is immediate; prefetch is background.** `switchKB`
   navigates right away and keeps `api.prefetchKnowledgeDetail` fire-and-forget.
   The detail page already seeds state from `knowledgeDetailCache`
   (`createKnowledgeDetailState(kbName, cached)`), so no first-frame empty
   state occurs. The `openingKB`/request-gate machinery is removed to avoid a
   lingering "正在打开…" state. Alternative (blocking prefetch) was rejected
   because it turns click latency into network latency.

2. **Detail page loads core + on-demand graph/entities.** Mount fetches
   documents/stats via the prefetch cache and upload tasks only. The graph tab
   triggers `getEntitiesForKB` + `getGraphForKB` with an explicit loading
   state. d3 is lazy-loaded through a module-level cached promise
   (`utils/lazyD3.js` exporting `loadD3()`); call sites (`drawGraph`, zoom and
   force handlers) `await loadD3()` on first use. This avoids extracting a
   large `GraphPanel` component (high prop-drilling risk) while still removing
   d3 from the initial detail chunk download. Vite assigns d3 its own vendor
   chunk.

3. **Polling becomes a visibility/task-aware loop with an internal task
   snapshot.** The panel-gated 3s task poll is insufficient as the gate source
   because closing the upload panel freezes `serverTasks`. The new 15s loop
   refreshes `getUploadTasks()` inside the loop, uses it as the gate, polls
   core data only while non-terminal tasks exist, performs one final
   `loadKBData` when tasks transition to all-terminal, stops when hidden
   (`document.hidden`), and refreshes graph/entities only while the graph tab
   is active. Visibility restore triggers an immediate check. Existing abort/
   generation guards (`genRef`, `AbortController`) remain.

4. **Global stats become a TTL-cached, route-scoped, KB-keyed request.**
   `api.js` exposes a cached stats getter (30s TTL, in-flight dedupe, keyed by
   `currentKB`, never caching the empty early return, invalidated on auth
   generation change — mirroring `kbListCache`). `App.jsx` calls it only for
   `/` and `/knowledge*` routes and skips while the tab is hidden.

5. **Suspense timeout fallback is preserved.** `key={location.pathname}` on the
   route surface is retained (per review S2) so `SuspenseWithTimeout` resets on
   each navigation; without it a hung chunk download would leave the app on the
   loader forever. The route remount cost is accepted; no scroll-reset behavior
   is added (out of scope).

6. **Entry de-bloat.** Remove framer-motion from `App.jsx` (toast, user menu,
   loader become CSS transitions; exit animations are intentionally dropped —
   the toast timer already owns unmount); keep it in lazy page chunks that
   still use it. Self-host Inter/JetBrains Mono via `@fontsource` (weights
   400/500/600, italic 400, JetBrains Mono 400/500). CSS font stacks stay the
   same.

7. **Deployment caching.** nginx adds immutable caching for `/assets/` and
   `no-cache` for `index.html`; both new locations repeat the server-level
   security headers because nginx does not inherit `add_header` from the server
   block once a location defines its own.

8. **Epoch sync becomes non-blocking but self-closing.** `main.jsx` renders
   first, then runs `synchronizeSystemDataEpoch()` in the background and
   reloads immediately if it reports a change (instead of waiting for the 15s
   monitor heartbeat).

## Risks / Trade-offs

- [Graph tab first open shows a brief skeleton] → Accepted trade-off; document
  tab gets the speed win and skeletons are explicit; graph chunk is small.
- [Removing framer-motion from App.jsx drops exit animations] → Accepted; CSS
  transitions mirror entry animations; pages keep framer-motion.
- [TTL-cached stats can be stale up to 30s] → Cockpit chips are decorative; KB
  list page has its own stats flow and invalidates on mutations.
- [Lazy d3 adds an await at call sites] → `loadD3()` caches the module promise;
  only graph-tab code paths touch it.
- [Self-hosted fonts add repo assets] → Only woff2 subsets, hashed and
  immutable; removes an external render-blocking dependency.
