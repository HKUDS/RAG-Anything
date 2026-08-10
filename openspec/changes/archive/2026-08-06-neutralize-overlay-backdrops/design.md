## Context

Overlay backdrops across the frontend currently use blue tints in two places:
Tailwind classes `bg-sky-900/20` / `bg-sky-900/25` on overlay elements in
`KnowledgePage.jsx`, `AgentsPage.jsx`, `WorkflowPage.jsx`, and
`KnowledgeDetailPage.jsx`; and navy `rgba(8,30,56,…)` / `rgba(12,74,110,…)`
backgrounds in `index.css` for `.agent-config-overlay`, `.side-drawer-layer`,
`.user-dialog-layer`, and `.user-dialog-layer--confirmation`. The
`.agent-config-overlay::after` bottom gradient is also slate-blue
(`rgba(15,23,42,…)`) in light mode while its dark mode is already neutral.

Blur for the Tailwind-class overlays comes from one centralized rule in
`index.css` matching those exact class combinations with
`backdrop-filter: blur(8px)`; the graph modals in `KnowledgeDetailPage.jsx`
receive the same blur through the descendant selector. The agent-config
overlay has its own `blur(8px)`.

## Goals / Non-Goals

**Goals:**
- Remove the blue hue from every overlay backdrop, including the
  agent-config overlay decoration.
- Preserve the exact blur behavior (`blur(8px)`) where it exists today.
- Keep the same alpha values so dimming level is unchanged (hue only).

**Non-Goals:**
- No changes to modal panels, cards, badges, or other blue accent colors.
- No new blur on overlays that currently have none (side drawer, user dialog layers).
- No API, backend, database, or dependency changes; no dark-mode variants added.

## Decisions

- Replace `bg-sky-900/20` → `bg-black/20` and `bg-sky-900/25` → `bg-black/25`
  on overlay elements, keeping existing companion classes such as
  `dark:bg-black/40` and `backdrop-blur-sm` untouched.
- Update the centralized blur rule selectors from the sky variants to the
  black variants (`.fixed.inset-0.bg-black\/25`,
  `.fixed.inset-0.bg-black\/20`, `.fixed.inset-0 .bg-black\/20`) so the same
  elements keep `blur(8px)`.
- Replace navy overlay `rgba()` backgrounds with `rgba(0,0,0,…)` at identical
  alpha values (`.agent-config-overlay` 0.24, `.side-drawer-layer` 0.22,
  `.user-dialog-layer` 0.22, `.user-dialog-layer--confirmation` 0.28), and
  the `.agent-config-overlay::after` light-mode gradient
  `rgba(15,23,42,0.10/0.16)` → `rgba(0,0,0,0.10/0.16)`.
- Pure black matches the established design-system rule that overlays and
  shadows use pure-black transparency without a blue tint.

## Risks / Trade-offs

- Missed centralized selector would silently drop blur → mitigated by updating
  the selector in the same change and verifying with a residual search plus a
  production build.
- `bg-black/20` is subtle in dark mode, but no dimmer than the previous
  `bg-sky-900/20` behavior → acceptable, no visual regression.
- Residual search for `bg-sky-900/2*` will also match non-overlay usages
  (badges/cards) → search must be scoped to `inset-0` overlay contexts.