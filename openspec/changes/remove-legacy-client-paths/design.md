## Context

The active autorepair router already exposes the protected code-parser route.
The frontend still calls the retired manufacturing path, while a separate upload
page is no longer routed or imported.

## Goals / Non-Goals

**Goals:**
- Keep the G-code editor functional through the active authorized route.
- Remove only client code proven unreachable or unused.

**Non-Goals:**
- Do not alter backend routes, response schemas, permissions, or general SSE
  handling in this change.

## Decisions

- Change the editor path in place so its existing `api.post` authentication and
  error semantics remain intact.
- Remove only unused page state and handlers from the autorepair page; retain
  the mounted editor and result callback.

## Risks / Trade-offs

- [A hidden consumer uses the retired upload page] → verify no import or route
  reference before deleting it and rely on the active knowledge-detail upload.
- [The old frontend spec names a retired route] → update its normative client
  requirement in the same change.
