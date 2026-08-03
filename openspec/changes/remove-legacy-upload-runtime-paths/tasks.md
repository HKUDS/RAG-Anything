## 1. Snapshot-only worker

- [x] 1.1 Remove the worker-local RAG factory and obsolete parser helper.
- [x] 1.2 Remove snapshot-derived configuration from subprocess construction and worker CLI parsing.
- [x] 1.3 Keep queue/retry transport compatibility while ensuring task snapshots remain authoritative.

## 2. Regression coverage

- [x] 2.1 Move worker-factory assertions to the service factory and retain preflight-provider coverage.
- [x] 2.2 Add worker and subprocess assertions for snapshot-only configuration.
- [x] 2.3 Run focused upload and worker tests.

## 3. Documentation

- [x] 3.1 Update PROJECT_SUMMARY.md with the completed behavior and validation result.
