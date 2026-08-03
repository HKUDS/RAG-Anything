## Why

The repository still tracks root-level one-off and legacy entrypoints that construct RAG instances outside the current Router -> Service -> Core boundary, or can overwrite and start a second server implementation. They are unreferenced by supported workflows yet can bypass RBAC, task snapshots, and durable upload lifecycle safeguards.

## What Changes

- Remove the unused `server.py.integration-backup` backup server and `_apply_changes.py` import-time source rewriter.
- Remove `query.py` and `upload_and_query.py`, which construct RAG directly instead of using authenticated APIs and service-layer policy.
- Remove only `worker_output.txt`, `.tmp-redesign-full-suite.xml`, `38692`, and `cd`: confirmed root output files with no source or test references.
- Add root-anchored ignore rules and source-contract coverage so the four output files are not accidentally recommitted.
- Mark the historical changelog entries for the retired direct-RAG CLIs as unavailable and point operators to the authenticated application surface.
- Add focused regression checks that assert these unsafe legacy entrypoints and generated files are not restored to the supported source surface.
- Record the deletion evidence and unverified external credential rotation requirement in the project summary.

## Capabilities

### New Capabilities
- `root-entrypoint-isolation`: The supported runtime surface excludes obsolete root-level server, source-rewriter, and direct-RAG scripts that bypass the application boundary.

### Modified Capabilities

- None.

## Impact

- Affected files: `server.py.integration-backup`, `_apply_changes.py`, `query.py`, `upload_and_query.py`, `worker_output.txt`, `.tmp-redesign-full-suite.xml`, `38692`, and `cd`.
- No HTTP endpoint, database migration, RBAC role, or supported import compatibility wrapper changes.
- Historical one-off CLI invocation through the removed root scripts is intentionally retired; supported access remains through the authenticated application APIs and UI.
- `rag_storage_kb_meta.json` and `sse_stress_summary.json` are out of scope: they still have service/test ownership and need separate changes before any version-control cleanup.
- Deleting the already-removed credential-bearing test does not revoke a credential retained in Git history; rotation status is unknown until the credential owner provides evidence.
