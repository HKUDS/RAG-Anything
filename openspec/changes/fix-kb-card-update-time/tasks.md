## 1. List Timestamp Contract

- [x] 1.1 Return canonical and compatibility update timestamps from `/kb/list` with creation fallback.
- [x] 1.2 Centralize the frontend timestamp fallback and use it for card display and time sorting.

## 2. Metadata and Historical Recovery

- [x] 2.1 Add manifest-managed migration 031 to remove the legacy trigger and recover suspect duplicate timestamp groups.
- [x] 2.2 Preserve full metadata snapshot conflict semantics and add regression coverage for existing KB timestamps.

## 3. Verification and Records

- [x] 3.1 Add focused backend, frontend, and migration contract tests.
- [x] 3.2 Run focused checks, OpenSpec validation, and diff validation; record environment-limited release evidence.
- [x] 3.3 Update `PROJECT_SUMMARY.md` with the repair result, migration requirement, and validation status.
