## 1. Overlay color changes

- [x] 1.1 Switch Tailwind overlay classes from `bg-sky-900/20` / `bg-sky-900/25` to `bg-black/20` / `bg-black/25` in KnowledgePage.jsx, AgentsPage.jsx, WorkflowPage.jsx, and KnowledgeDetailPage.jsx.
- [x] 1.2 Replace navy overlay `rgba()` backgrounds with equal-alpha neutral black in index.css (.agent-config-overlay, .side-drawer-layer, .user-dialog-layer, .user-dialog-layer--confirmation).
- [x] 1.3 Neutralize the `.agent-config-overlay::after` light-mode gradient (`rgba(15,23,42,…)` → `rgba(0,0,0,…)`).

## 2. Blur preservation

- [x] 2.1 Update the centralized backdrop-filter rule selectors to the new `bg-black/*` classes so `blur(8px)` keeps applying to the same overlays.

## 3. Verification

- [x] 3.1 Run frontend unit tests (`npm run test:unit`) as a smoke regression (note: unit tests do not assert CSS) and production build (`npm run build`).
- [x] 3.2 Search for residual blue overlay classes on `inset-0` overlay elements (`bg-sky-900/2*` in fixed/absolute inset-0 contexts) and navy overlay `rgba()` backgrounds (`rgba(8,30,56` / `rgba(12,74,110` / light-mode `rgba(15,23,42` in overlay rules); confirm none remain, ignoring non-overlay badge/card usages.
- [x] 3.3 Spot-check overlays visually in light and dark mode (KB delete/create, agent delete, workflow dialogs, graph modals, user dialogs, side drawer, agent config) to confirm neutral backdrop and preserved blur.
- [x] 3.4 Update PROJECT_SUMMARY.md with the completed behavior and validation result, then archive the change.