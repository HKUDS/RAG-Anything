## 1. Backend settings model

- [x] 1.1 Add sparse KB ingestion-default helpers over `kb_metadata.extra` with normalization, revision handling, and preservation of unrelated metadata.
- [x] 1.2 Add the dedicated KB layer to settings resolution after personal settings and before request overrides, including source and constraint projection.
- [x] 1.3 Add GET/PUT `/kb/{kb}/ingestion-settings` with KB access, `kb:write`, validation, optimistic revision, and sanitized response shaping.

## 2. Upload snapshot integration

- [x] 2.1 Load KB ingestion defaults in the shared upload snapshot helper and resolve all five upload routes through the immutable task snapshot.
- [x] 2.2 Preserve empty-query inheritance, request override compatibility, retry behavior, and old task snapshots.

## 3. Frontend experience and permissions

- [x] 3.1 Rename and clarify the personal ingestion section as upload defaults without changing capability projection.
- [x] 3.2 Add KB ingestion-default loading, effective-source display, revisioned save/reset, and error states to the knowledge detail page.
- [x] 3.3 Update the upload panel and API client to show KB defaults, personal fallback, and one-upload overrides; hide write controls and catalog loading for students.

## 4. Verification and project records

- [x] 4.1 Add backend precedence, endpoint, revision, validation, and five-role upload snapshot tests.
- [x] 4.2 Add frontend API/source-summary and five-role visibility tests.
- [x] 4.3 Run focused backend/frontend tests, strict OpenSpec validation, syntax checks, and `git diff --check`; record any build environment blocker.
- [x] 4.4 Update `PROJECT_SUMMARY.md` with current facts, verification results, and the task record without secrets or generated artifacts.
