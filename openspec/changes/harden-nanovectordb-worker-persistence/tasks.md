## 1. NanoVectorDB Finalization

- [x] 1.1 Persist Worker-owned NanoVectorDB stores without discarding vectors because of a stale local update flag.
- [x] 1.2 Raise a bounded error when a vector-store persistence callback does not succeed.

## 2. Regression Coverage

- [x] 2.1 Add focused tests for successful persistence, stale flags, and failed VDB callbacks.
- [x] 2.2 Verify Worker finalization propagates a persistence failure rather than reporting completion.

## 3. Verification and Handoff

- [x] 3.1 Run focused tests, compilation, diff checks, and OpenSpec validation.
- [x] 3.2 Update `PROJECT_SUMMARY.md` with local evidence and the cloud acceptance boundary.

## 4. Cross-process cache invalidation

- [x] 4.1 Add a retirement mode that releases a stale pre-Worker core without
  persisting its file-backed vector stores.
- [x] 4.2 Use the discard mode only when resolving a Worker-written document;
  preserve ordinary eviction and shutdown persistence.
- [x] 4.3 Add regression coverage for discard-mode vector skipping and normal
  persistence compatibility.
- [x] 4.4 Update the project summary with the discovered overwrite race and
  deployment acceptance boundary.
