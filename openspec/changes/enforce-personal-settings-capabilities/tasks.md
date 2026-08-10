## 1. Capability Policy And Settings Projection

- [x] 1.1 Add a shared, permission-derived ordered task-section policy and
  projection helpers without role-name branching.
- [x] 1.2 Filter personal-settings reads/options by available sections and
  reject denied section writes before validation or persistence.

## 2. Request And Legacy API Boundaries

- [x] 2.1 Require the model capability for legacy personal VLM preference
  reads and writes while preserving the generic model-profile catalog.
- [x] 2.2 Thread permitted sections through agent and every upload-snapshot
  enqueue boundary so new work ignores denied stored overrides and prior
  durable snapshots remain unchanged.

## 3. Preferences Interface

- [x] 3.1 Add pure frontend section-access helpers and tests for built-in and
  custom permission sets, server intersections, grouping, hash recovery, and
  request planning.
- [x] 3.2 Render the preferences navigation, sections, observer, hash, error
  recovery, and deferred data requests from available sections; remove the
  generic model-catalog fallback.
- [x] 3.3 Replace personal-settings copy that advertises unavailable model or
  task controls and preserve responsive accessible navigation behavior.

## 4. Regression And Closeout

- [x] 4.1 Add backend coverage for projection, 403 behavior, downgrade
  resolution, and immutable queued snapshots; add frontend source contracts.
- [x] 4.2 Run focused backend and frontend tests, Vite build, strict OpenSpec,
  project-summary checks, and `git diff --check`; record environment limits.
- [x] 4.3 Update `PROJECT_SUMMARY.md` with the completed behavior, validation,
  and risk record without overwriting unrelated work.
