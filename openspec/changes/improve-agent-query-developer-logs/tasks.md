## 1. Query Journey Logging

- [x] 1.1 Extend `QueryTiming` with bounded, deterministically ordered completed
  stage tracking and one terminal `QUERY_JOURNEY` summary emission.
- [x] 1.2 Ensure terminal summary logging remains exactly once for success,
  error, timeout, and cancellation paths without changing metrics or existing
  `QUERY_TIMING` records.

## 2. Verification

- [x] 2.1 Add focused unit coverage for summary format, ordering, terminal
  idempotence, cross-trace isolation, compatibility records, and content-free
  privacy.
- [x] 2.2 Run focused tests, `py_compile`, `git diff --check`, strict OpenSpec
  validation, and the project summary quality check.

## 3. Project Record

- [x] 3.1 Update `PROJECT_SUMMARY.md` with the final behavior, validation
  evidence, and any remaining live-runtime verification boundary.
