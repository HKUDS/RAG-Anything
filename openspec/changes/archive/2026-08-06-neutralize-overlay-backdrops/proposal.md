## Why

Modal/dialog overlay backdrops across the frontend use blue-tinted colors
(`bg-sky-900/20` / `bg-sky-900/25` and navy `rgba(8,30,56,…)` /
`rgba(12,74,110,…)`), so the dimmed page background reads as blue. The
Neutral Modern design system mandates pure-black transparency for overlays
and shadows, without any blue hue.

## What Changes

- Replace every overlay backdrop blue tint with an equal-alpha neutral black,
  so the dimming level is unchanged and only the hue is removed.
- Preserve the existing backdrop blur on every overlay that already has it:
  Tailwind-class overlays keep `blur(8px)` via the centralized rule, and the
  agent-config overlay keeps `blur(8px)` from its own rule.
- Neutralize the agent-config overlay bottom gradient decoration in light
  mode (`rgba(15,23,42,…)` → `rgba(0,0,0,…)`), matching its already-neutral
  dark-mode gradient.
- Touch overlay backgrounds only; modal panels, cards, badges, and other
  blue accent colors are unchanged.

## Capabilities

### New Capabilities

- `frontend-overlay-backdrop`: Modal/dialog overlay backdrops render as a
  neutral black tint (no blue hue) at the established alpha, keeping the
  existing blur behavior.

### Modified Capabilities

- (none)

## Impact

- Frontend only: `frontend/src/pages/KnowledgePage.jsx`,
  `frontend/src/pages/AgentsPage.jsx`, `frontend/src/pages/WorkflowPage.jsx`,
  `frontend/src/pages/KnowledgeDetailPage.jsx`, and
  `frontend/src/index.css` (overlay rules).
- No API, backend, database, or dependency changes.