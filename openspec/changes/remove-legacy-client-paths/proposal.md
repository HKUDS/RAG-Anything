## Why

The frontend retains an unreachable upload page and a G-code editor that calls
the retired manufacturing endpoint despite the equivalent RBAC-protected
autorepair endpoint already being available.

## What Changes

- Remove the unreferenced legacy upload page.
- Route G-code and PLC parsing through the existing autorepair endpoint.
- Remove obsolete local code-parse state from the autorepair page.
- Keep request authentication and existing user-visible behavior intact.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frontend-visualization`: code parsing uses the active autorepair API path.
- `router-manufacturing-split`: client references describe the active
  autorepair route rather than the retired manufacturing route.

## Impact

`frontend/src/components/GCodeEditor.jsx`,
`frontend/src/pages/AutoRepairAgentPage.jsx`, the retired upload page, and
focused frontend source guards change. No backend route or API response changes.
