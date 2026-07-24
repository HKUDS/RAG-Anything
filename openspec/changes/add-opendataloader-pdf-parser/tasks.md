## 1. Scope, Compliance, and Runtime Baseline

- [ ] 1.1 Record the exact OpenDataLoader PDF `v2.5.0` source revision and hashes for the Python wheel and bundled JAR. Scan the final wheel/JAR/container into CycloneDX or SPDX SBOMs, reconcile actual Maven/Python versions against upstream notices (including the veraPDF version discrepancy), and make unknown licenses, `NOASSERTION`, missing notices, or unresolved versions a redistribution blocker.
- [x] 1.2 Add an `opendataloader` optional extra pinned to `opendataloader-pdf==2.5.0` with verified hashes in `pyproject.toml` and `setup.py`, regenerate `uv.lock` without unrelated upgrades, and do not add it to default `requirements.txt`.
- [ ] 1.3 Add an opt-in `Dockerfile` build target/argument that installs JRE 17 headlessly and the `opendataloader` extra while the default image preserves its current dependency/runtime footprint; assert Java and SDK versions in the opt-in build verification.
- [ ] 1.4 Preserve pinned `LICENSE`, `NOTICE`, third-party notice files, component license texts, and immutable corresponding-source references at a stable OSS-notices path in redistributed artifacts; document that this approval covers the new integration only.
- [x] 1.5 Add non-secret configuration documentation to `env.example` and deployment documentation for optional `PDF_PARSER`, Java heap/thread caps, maximum pages/input bytes, parser timeout, concurrency, and output retention. Do not modify `.env`, and leave global parser defaults unchanged.
- [ ] 1.6 Run a pinned-SDK contract spike against representative and blank-page fixtures to determine exact artifact names/schema, explicit page markers/status, table/image/formula shapes, and the bounding-box coordinate system. If batch artifacts cannot prove every page completed, specify and test a per-page strategy before continuing past the proof of concept.
- [ ] 1.7 Establish conservative canary limits using actual deployment capacity and document the operator procedure to set/clear `PDF_PARSER=opendataloader` without changing non-PDF routing.

## 2. Parser Adapter and Artifact Validation

- [ ] 2.1 Create `raganything/parser/opendataloader_parser.py` with `OpenDataLoaderParser(Parser)`, PDF-only method boundaries, a stable output-schema version, and a stable cache-identity method/property.
- [ ] 2.2 Implement `check_installation()` with independent Python-package and Java-version checks; return actionable errors for an absent package, missing Java executable, or Java version below the supported minimum without making network calls.
- [x] 2.3 Implement local fast-mode conversion through the official `opendataloader_pdf.convert()` API only. Use resolved paths and `Parser._unique_output_dir()`, request raw JSON plus page-marked diagnostic Markdown, use JSON as the sole normalization source, preserve upstream safety filters, and prohibit hybrid, remote, or `content_safety_off` options.
- [ ] 2.4 Enforce preflight PDF byte/page limits, JVM heap/thread limits, parser timeout, and concurrency. Terminate the entire converter process tree on timeout on supported Windows and container deployments, and emit bounded structured parser-stage errors.
- [ ] 2.5 Discover the expected JSON artifact deterministically, parse it with schema/type validation, reject missing/malformed/ambiguous output, and ensure all output reads are contained within the unique parser output directory.
- [ ] 2.6 Normalize elements to the existing contract: text with heading depth mapped to `text_level`, tables with `table_body`/compatible data, verified images with safe absolute `img_path`, and equations where representable. Convert one-based pages to zero-based `page_idx` and call the established public-media URL helper.
- [ ] 2.7 Resolve generated media without following an escape outside the document output root; reject traversal, symlink escape, and missing references, and emit a manifest-recorded text fallback instead of dereferencing unsafe media.
- [x] 2.8 Define and implement deterministic handling for unsupported/invalid upstream element types: retain a safe text fallback and provenance where possible; otherwise raise a clear validation error. Do not silently discard elements.
- [ ] 2.9 Atomically retain raw upstream JSON, normalized content identity, coverage, and per-element provenance beneath the parser output root. Normalize bbox as `[left,bottom,right,top]` in PDF points with bottom-left origin, keep `doc_status.metadata` lightweight, and integrate retry overwrite, document deletion, KB deletion, and retention cleanup.
- [x] 2.10 Build a `PageTrackedContent`-compatible manifest using local `pypdf` source count and trustworthy per-page proof from task 1.6, including blank pages. Never infer complete coverage solely from converter exit success and fail before any persistence with `pdf_page_coverage_incomplete` when proof is absent.

## 3. Parser Registry, Coverage Gate, Cache, and Worker Integration

- [ ] 3.1 Register `opendataloader` in `raganything/parser/__init__.py` through deterministic worker imports with lazy optional-dependency behavior; update public discovery/help and preserve all parser defaults.
- [ ] 3.2 Add optional `pdf_parser` configuration in `raganything/config.py` and parser initialization, then pass `PDF_PARSER` explicitly through `process_worker.py` and knowledge-base worker configuration. An unset value must preserve every current behavior.
- [x] 3.3 Update `DocProcessorMixin` to select an effective parser by extension: the PDF override for `.pdf` when configured, otherwise the global parser. Ensure DOCX, images, and other inputs continue through their existing parser/fallback paths.
- [x] 3.4 Generalize PDF coverage enforcement from the literal `parser == 'docling'` check to an effective-parser capability contract. Preserve Docling behavior and reject incomplete OpenDataLoader output before quality checks, cache, `doc_status` success, or storage.
- [ ] 3.5 Extend parse-cache keys and cached metadata with effective parser, package version, fixed fast mode, adapter schema version, and behavior-affecting options; version/mode changes must miss while validated identical output may hit.
- [ ] 3.6 Store only lightweight parser identity, page coverage, and relative sidecar references in cache/`doc_status.metadata`; do not expose arbitrary filesystem paths or add a public provenance API.
- [ ] 3.7 Integrate structured failure codes, task status, retry behavior, file lock, watchdog, and process-tree cleanup into the worker. Never run conversion in FastAPI request handling and never perform an implicit fallback.
- [ ] 3.8 Add structured logs/metrics for backend, package version, page/block count, elapsed time, and outcome category without document text, credentials, or disallowed paths.
- [ ] 3.9 Confirm all derived text still enters the existing injection scan and add no bypasses to RBAC, upload validation, locking, audit logging, or background-task draining.

## 4. Automated Tests

- [x] 4.1 Add isolated `tests/test_opendataloader_parser.py` fixtures for registration, installation probes, deterministic JSON-only mapping, order, duplicate headings, text/table/image/equation output, `text_level`, zero-based pages, normalized bbox, media URL attachment, sidecars, and cache identity.
- [ ] 4.2 Add negative tests for missing Java/package, old Java, non-PDF input, non-fast options, size/page limits, SDK exception/timeout, process-tree cleanup, invalid JSON/schema, partial/blank/duplicate coverage, unknown types, missing media, traversal/symlink escape, and atomic cleanup.
- [x] 4.3 Extend parser wiring/registry/config tests to prove `PDF_PARSER=opendataloader` affects only PDFs, DOCX/images retain the global parser, an unset override preserves defaults, and module import works without Java or the optional SDK.
- [x] 4.4 Extend `tests/testparser_kwargs.py` or a focused replacement suite to prove the generic page-coverage gate preserves current Docling coverage behavior and rejects incomplete OpenDataLoader output before cache or insertion.
- [ ] 4.5 Add parse-cache tests proving a package/version/options identity change reparses the document while an unchanged identity reuses only validated output.
- [ ] 4.6 Add new-process worker/task tests proving configuration propagation, conversion/coverage/resource failures become structured parser-stage failures, retry semantics remain, no partial chunks exist, and registered background work is drained.
- [ ] 4.7 Add a security regression proving OpenDataLoader-produced text enters the existing ingestion injection-defense path and no document text, secret, or unsafe external path is written to parser telemetry/provenance.
- [x] 4.8 Add an opt-in, skipped-by-default real-stack test requiring the optional extra, Java, and local sanitized PDFs including a blank page; assert installation, explicit complete coverage, containment, normalized output, and no network/model download.
- [ ] 4.9 Build both default and opt-in container variants. Assert the default footprint/Docling behavior remains, and the opt-in image has Java 17, pinned SDK, healthy service, non-hybrid dependency posture, and a real PDF CLI/adapter smoke conversion.

## 5. Documentation, Evaluation, and Controlled Rollout

- [ ] 5.1 Document the PDF override, Java/extra prerequisites, fast-only security posture, resource controls, artifact/sidecar lifecycle, cache behavior, failure codes, optional build, license evidence path, and exact rollback/re-ingestion procedure; update relevant CLI/batch examples without adding a frontend selector.
- [ ] 5.2 Prepare an approved 30-50 document corpus outside the source tree covering Chinese digital/scanned PDFs, contracts, multi-column papers, complex tables, images, formulas, tagged/blank/long PDFs, encrypted/malformed PDFs, and injection tests; record page counts and expected notes.
- [ ] 5.3 Execute an isolated canary comparison against Docling and MinerU using the corpus. Record full-page coverage, text reading order, table usability, image association, injection handling, parser success/failure reason, P50/P95 duration, and peak worker memory.
- [ ] 5.4 Require written go/no-go evidence: test report, artifact hashes, image digest, SBOM, notice/source hashes, dependency reconciliation, legal approval, zero coverage/partial-ingestion defects, no security regression, and acceptable quality/resource results.
- [ ] 5.5 Deploy only to isolated staging with a separate working directory/KB and `PDF_PARSER=opendataloader`. Do not claim percentage-based same-cluster canary routing, bulk reparse, or touch production KBs without a separately designed selector/allowlist.
- [ ] 5.6 Drill rollback by clearing/restoring `PDF_PARSER` and restarting workers; verify new PDFs use the prior parser and non-PDF routing is unchanged. Preserve sources/artifacts and document supported deletion/re-ingestion for already-ingested OpenDataLoader documents that must be rebuilt.

## 6. Final Verification

- [ ] 6.1 Run the focused parser, processor, worker, injection-defense, and upload-task test suites; run the repository lint/format/type checks required by the changed modules and record exact commands/results.
- [ ] 6.2 Review the final diff for accidental global/default parser changes, optional dependency leakage into defaults, missing hashes/notices, unsafe command/path/symlink handling, forbidden hybrid/remote options, incomplete process-tree/output cleanup, and public provenance-path exposure.
- [x] 6.3 Run `openspec validate add-opendataloader-pdf-parser --strict` and resolve every validation failure before requesting implementation review or beginning `/opsx:apply`.
