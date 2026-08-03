## ADDED Requirements

### Requirement: Supported root runtime surface excludes retired direct-RAG entrypoints
The repository SHALL NOT ship `server.py.integration-backup`, `_apply_changes.py`, `query.py`, or `upload_and_query.py` as executable root-level entrypoints. Supported application access SHALL continue through the maintained server and authenticated Router -> Service -> Core path.

#### Scenario: Repository source surface is checked
- **WHEN** repository source-contract tests inspect the root runtime paths
- **THEN** the four retired entrypoints are absent and `server.py` remains present

### Requirement: Generated root output is excluded from maintained source
The repository SHALL exclude `worker_output.txt`, `.tmp-redesign-full-suite.xml`, `38692`, and `cd` from its maintained root source surface with root-anchored ignore rules. The change diff SHALL remove the current tracked copies; a subsequent commit will record their removal from version control.

#### Scenario: Source-contract test inspects generated paths and ignore rules
- **WHEN** repository source-contract tests inspect the confirmed generated root paths
- **THEN** none of the four paths is present and each exact root path is ignored without ignoring same-named nested source files

### Requirement: Existing JSON ownership remains unchanged
The isolation change SHALL NOT remove, ignore, or otherwise alter the ownership of `sse_stress_summary.json` or the existing ignored `rag_storage_kb_meta.json` service mirror.

#### Scenario: Source-contract test protects excluded JSON paths
- **WHEN** repository source-contract tests evaluate the excluded JSON paths
- **THEN** `sse_stress_summary.json` remains present, tracked, and not ignored, while `rag_storage_kb_meta.json` remains present and ignored by its pre-existing rule
