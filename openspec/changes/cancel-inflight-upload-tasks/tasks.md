## 1. Cancellation Lifecycle

- [x] 1.1 Add migration `024` documenting `cancelling` in the upload task state lifecycle.
- [x] 1.2 Add transactional cancellation transition and task-scoped cleanup coordinator in the knowledge-base service.
- [x] 1.3 Make queue, worker finalization, task state, retry handling, and startup recovery reject cancelling/deleted work.

## 2. API and Upload Drawer

- [x] 2.1 Extend upload-task listing and deletion responses for cancellable statuses, `202 cancelling`, and idempotent polling.
- [x] 2.2 Add accessible processing/retry deletion confirmation and cancellation-in-progress feedback to the knowledge-base upload drawer.
- [x] 2.3 Route document-table deletion of unfinished uploads through durable task provenance and the centered shared confirmation dialog.
- [x] 2.4 Route explicit active task provenance through cancellation even when the document-list capability is stale or absent.

## 3. Verification and Documentation

- [x] 3.1 Add focused backend regressions for cancellation visibility, acceptance, and cancellation-state write protection.
- [x] 3.2 Run targeted backend tests, frontend unit tests, Vite build, OpenSpec validation, and diff checks.
- [x] 3.3 Update `PROJECT_SUMMARY.md` with the implemented lifecycle, validation result, and residual deployment risk.
