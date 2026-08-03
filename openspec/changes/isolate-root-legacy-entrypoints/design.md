## Context

The deployed application enters through `server.py` and uses Router -> Service -> Core boundaries. Four root scripts predate that structure: a full backup server, an import-time source rewriter, and two RAG-direct CLI workflows. Four tracked files are generated root output rather than source. Static-reference and Git-history checks found no supported workflow invoking them.

## Goals / Non-Goals

**Goals:**

- Reduce the supported root runtime surface to the maintained application entrypoints.
- Eliminate known paths that create RAG instances without authentication, RBAC, task snapshots, or durable upload lifecycle controls.
- Remove only confirmed generated output with no source or test ownership, and prevent its accidental restoration.
- Leave durable runtime artifacts, data imports, migrations, and supported compatibility wrappers untouched.

**Non-Goals:**

- Replacing the retired direct-RAG CLIs with a new public CLI or HTTP API.
- Removing tracked ODL/DOCX artifacts, `rag_storage_kb_meta.json`, `sse_stress_summary.json`, `agent_templates.json`, or supported operations/data-import scripts.
- Altering HTTP API paths, database schema, RBAC behavior, or production data.

## Decisions

### Delete obsolete implementations instead of adapting them

`server.py.integration-backup` is a second application composition and `_apply_changes.py` writes into `server.py` when imported. Retaining either as an executable or adapting it to current internals would create a second supported maintenance path. Git history preserves the recovery source, so the files will be deleted.

`query.py` and `upload_and_query.py` construct `RAGAnything` directly with local storage and environment credentials. They cannot be safely made equivalent to the authenticated service by small edits: they would need account identity, permission checks, persistent upload-task creation, cancellation, and settings snapshots. They will be retired rather than relabeled as supported tooling.

### Treat root outputs as generated evidence, not source

`worker_output.txt`, `.tmp-redesign-full-suite.xml`, `38692`, and `cd` are tracked output/empty files with no code or test references. They will be removed after final path/reference verification. This change does not remove `rag_storage_kb_meta.json`, which remains a service-written mirror, or `sse_stress_summary.json`, whose root default is still owned by the Locust test tool.

### Make absence testable without coupling production code to tests

A focused repository-contract test will assert the obsolete paths are absent and that the maintained server entrypoint remains. This prevents an accidental reintroduction during conflict resolution without changing runtime behavior.

## Risks / Trade-offs

- [An external operator invokes a retired root CLI] -> Git history and the OpenSpec record identify the removal; supported workflows remain the authenticated UI/API.
- [A generated file was external audit evidence] -> Only files with no repository references and Git-backed provenance are removed; ODL/DOCX artifacts remain out of scope.
- [Tests turn a repository layout into a brittle interface] -> Assert only the explicitly retired unsafe entrypoints, not general file organization.
- [The exposed token from the already-removed test is still valid] -> Record that revocation/rotation is an external operational action, not a source-code change.

## Migration Plan

1. Re-run static-reference and tracked-path checks immediately before deletion.
2. Delete only the named obsolete root files and add the focused regression test.
3. Run focused Python tests, strict OpenSpec validation, summary validation, and `git diff --check`.
4. Roll back by restoring the named files from Git history only if a verified supported consumer is found; do not restore an unsafe direct-RAG workflow as a production path.

## Open Questions

- None for this bounded removal. Credential revocation requires the external credential owner.
