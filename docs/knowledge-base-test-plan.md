# Knowledge Base Test Plan

This plan is the acceptance baseline for knowledge base completeness in this repo.

## Scope

- KB CRUD: list, create, switch, delete, ownership visibility.
- Upload lifecycle: accept, queue, process, fail, retry, delete queued task.
- Document lifecycle: list, chunk inspect, download, delete, absence after delete.
- Chunking: `fixed_size`, `recursive`, `sentence`, `structure`, `semantic`, `agentic`.
- Modal coverage: DOCX, PDF, video.
- Multimodal: image, table, equation, video switches and evidence in chunks.
- Graph and stats: entities, graph nodes/edges, per-KB stats, batch stats consistency.
- Agent binding: each new agent must bind to the same `testNN` KB.
- RBAC: low-privilege negative checks for KB/agent write access.

## Samples

- DOCX: `D:\Users\98014\Desktop\人工智能222+2022010940231\上报学校存档\1.Word\3.开题报告.docx`
- PDF: `D:\Users\98014\Desktop\人工智能222+2022010940231\上报学校存档\2.PDF\3.开题报告.pdf`
- Video: `D:\Users\98014\Downloads\8、车辆内部检查 (1).mp4`

## Naming Rule

- New KBs: `test01`, `test02`, `test03` ...
- New agents: same number as the KB, for example agent `test01` bound to KB `test01`.

## Matrix

- Full matrix: 6 strategies x 3 file types = 18 scenarios.
- Smoke matrix: `fixed_size+docx`, `structure+pdf`, `fixed_size+video`.

## Scenario Assertions

- Upload returns `task_id` and target KB name.
- Upload task moves through queue/process terminal states.
- Document appears in `/knowledge/documents` for the target KB.
- `/knowledge/documents/{doc_id}/chunks` returns non-empty chunks.
- Chunk order is monotonic by `chunk_order_index`.
- Chunk record keeps metadata fields such as `file_path`, `tokens`, `is_multimodal`, `original_type`, `page_idx`, `media_path`, `media_url` when applicable.
- `/knowledge/stats` reports non-zero documents and chunks after successful ingestion.
- `/knowledge/stats/batch` matches `/knowledge/stats` for the same KB.
- `/knowledge/entities` and `/knowledge/graph` are coherent with stats.
- If stats show entities > 0, graph should expose nodes.
- Agent created for the scenario remains bound to the same KB.
- Report must distinguish `failed` (product regression) from `blocked` (environment or external dependency).

## Extra Coverage

- Duplicate upload protection in the same KB.
- Failed-document retry using an invalid synthetic PDF sample.
- Download and delete after a successful ingestion.
- Admin-only multimodal reprocess endpoint behavior.
- Optional RBAC drift audit: compare actual low-privilege behavior with expected deny rules.

## Result Policy

- `passed`: no error-level assertion failed.
- `failed`: at least one error-level assertion failed and evidence points to product behavior.
- `blocked`: at least one error-level assertion failed but the root cause is infrastructure, runtime dependency, permission, or external LLM/VLM connectivity.
- `skipped`: the probe could not run meaningfully because prerequisite capability was not available.

## Expected Risks To Watch

- Encoding drift for Chinese file names in console output.
- Video processing may depend on optional runtime features and can be slower than document parsing.
- Some sample files may contain limited multimodal elements; when that happens, multimodal checks should become warnings, not false positives.
- Current repo role names may differ from older `admin/editor/viewer` wording; validate against actual role records returned by `/admin/roles`.
- The suite should preserve server log excerpts so blocked results can be traced to concrete runtime evidence.

## Execution Notes

- Use the automation script in `scripts/kb_regression_suite.py` for helper logic, naming, sample defaults, and matrix selection.
- Prefer `--profile full` for acceptance and `--profile smoke` for quick checks.
- Use `--skip-probes` when you want to validate only the scenario matrix first, then rerun probes separately.
- When possible, run with `--server-log <path>` so the JSON report captures log excerpts and root-cause clues.
- Keep created `testNN` resources when investigating failures; clean them up only after collecting evidence.

## Observed Smoke Findings

- Smoke evidence file: `output/kb-regression/kb-regression-20260710-152745.json`.
- On July 10, 2026, real smoke execution exposed three concrete environment blockers that must stay in the acceptance baseline:
- `ffmpeg_permission_denied`: KB initialization for video processing can fail with `PermissionError: [WinError 5]` while probing ffmpeg.
- `llm_connectivity_blocked`: DOCX/PDF multimodal and entity stages can fail when OpenAI/VLM calls raise connection errors.
- `docling_resource_missing`: PDF parsing can fail because `docling_parse/pdf_resources/glyphs/standard/additional.dat` is missing.
- The first smoke run also showed a practical orchestration risk: if the API server dies mid-run, later scenarios become `api_server_unavailable` rather than clean product failures.

## Evidence To Retain

- Scenario-level JSON report.
- Task timelines with status/phase transitions.
- Document snapshots before and after delete/retry.
- Chunk payload excerpts showing metadata completeness.
- Stats, entities, graph, and agent binding responses.
