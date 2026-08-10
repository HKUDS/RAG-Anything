## Context

The personal-settings service stores sparse overrides for four task sections
while the browser renders a static settings navigation for every authenticated
user. The existing permission model already distinguishes the required
capabilities, but settings reads, writes, legacy VLM preferences, and request
resolution do not consume that distinction.

## Goals / Non-Goals

**Goals:**

- Derive one ordered section policy from live permissions at every server
  boundary and use a matching pure frontend policy for immediate UI convergence.
- Keep denied stored JSONB data intact while excluding it from read projections
  and new task/request resolution.
- Keep queued task settings snapshots immutable and retain the generic model
  profile catalog for its existing non-preference consumers.

**Non-Goals:**

- Do not change role definitions, permission constants, schema, migrations,
  platform policy, or generic model-catalog access.
- Do not display disabled controls or role names for unavailable settings.

## Decisions

### Canonical section policy

The backend will expose helpers that map a live permission set to ordered
sections: `models` requires `agent:write`; `ingestion`, `retrieval`, and
`runtime` require `kb:write`. Public browser/account/security controls are not
stored in the four-section API and stay available. This uses capabilities rather
than role names, so custom roles receive the correct intersection.

### Projection and write enforcement

The settings read and options endpoints will return `available_sections` and
only data belonging to those sections. Section PATCH performs the same live
permission check before validation or persistence and returns 403 when denied.
The legacy personal VLM preference endpoints require `agent:write`; the generic
`/model-profiles` catalog remains unchanged because KB configuration still uses
it independently.

### Permission-loss behavior

Resolution receives the permitted stored-section set at authenticated request
and enqueue boundaries. It masks only denied user-stored layers before applying
platform, resource, request, and index precedence. Thus a fresh request after a
downgrade inherits the platform value, while an existing durable task snapshot
continues to execute unchanged. This avoids destructive role-change writes and
preserves audit history.

### Frontend source of truth and recovery

The page intersects `available_sections` with its pure `hasPermission` policy,
then uses that ordered result for both navigation variants, mounted sections,
observer targets, hash selection, and lazy option/catalog requests. It does not
fall back to the generic model catalog. An absent or newly denied hash is
replaced with the first visible section; PATCH 403 reloads the projection and
removes denied drafts.

## Risks / Trade-offs

- [Permission data changes during an open page] -> Intersect server output with
  the current frontend permission state and reload after a denied PATCH.
- [Legacy stored values survive downgrade] -> Mask them only for fresh settings
  resolution; leave their row and prior task snapshots unchanged.
- [Projection contract surprises old callers] -> Preserve existing response
  fields for available sections, add `available_sections`, and keep paths and
  generic catalog behavior unchanged.
