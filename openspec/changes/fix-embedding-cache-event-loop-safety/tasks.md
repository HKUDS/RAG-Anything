## 1. Async Cache Safety

- [x] 1.1 Add loop-safe asynchronous cache read/write operations and route the asynchronous embedding wrapper through them.
- [x] 1.2 Preserve synchronous compatibility methods and best-effort cache degradation with redacted diagnostics.

## 2. Regression Coverage

- [x] 2.1 Add loop-affinity tests for cache hits and misses in the asynchronous embedding wrapper.
- [x] 2.2 Add cache read/write failure tests that verify direct embedding remains available.

## 3. Verification and Handoff

- [x] 3.1 Run focused tests, compilation, diff checks, and OpenSpec validation.
- [x] 3.2 Update `PROJECT_SUMMARY.md` with the failure mechanism, local validation, and cloud acceptance boundary.
