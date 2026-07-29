## Context

RAG-Anything dispatches document parsing through `get_parser()` and runs `parse_pdf()` from `DocProcessorMixin` in a background worker. One global parser configuration currently covers multiple file types. The normalized output contract is a list of `text`, `image`, `table`, and related blocks consumed by multimodal insertion. Docling currently has a special `PageTrackedContent` coverage gate; other parser output can otherwise enter the cache and storage without an equivalent PDF-page completeness proof.

OpenDataLoader PDF 2.5.0 is a PDF-only Python wrapper around a packaged Java JAR. It produces file artifacts and starts a JVM per conversion. Its useful output is JSON carrying semantic type, source-page number, bounding box, heading level, text/table data, and generated image references. The deployment image is Python-based and presently lacks Java.

Stakeholders are operators selecting a parser for a knowledge base, users depending on correct document retrieval, and maintainers responsible for security, licensing, resource usage, and recoverable uploads.

## Goals / Non-Goals

**Goals:**

- Add a pinned, explicitly selectable `opendataloader` PDF override without changing the global parser, non-PDF behavior, current defaults, or existing knowledge bases.
- Convert validated upstream artifacts into the existing content-list contract, retaining source-location provenance in a durable sidecar manifest.
- Ensure complete/valid parse output is required before caching or inserting content, with clear worker failure behavior.
- Make the backend safe to operate in the existing worker model: no request-path JVM calls, no remote/hybrid service, bounded runtime/resources, observable outcomes, and deterministic rollback.
- Produce a reproducible evaluation path against representative Chinese and complex PDFs.

**Non-Goals:**

- Replacing Docling, MinerU, Marker, or PaddleOCR; changing automatic parser selection; or reprocessing existing knowledge bases.
- Supporting Office, image, audio, video, encrypted-password handling beyond upstream's existing public API, PDF/UA enterprise features, or a new frontend parser selector.
- Enabling OpenDataLoader hybrid mode, running a separate hybrid server, sending document data to a remote service, or claiming that upstream benchmark results apply to this product.
- Adding coordinate-level citation UI in this change. The sidecar manifest is the stable hand-off for a later citation feature.

## Decisions

### 1. Add an opt-in PDF override, not a global replacement or hidden fallback

Create `OpenDataLoaderParser(Parser)` in `raganything/parser/opendataloader_parser.py` and expose it as the built-in name `opendataloader` through deterministic imports available to newly spawned workers. Add an optional `PDF_PARSER`/`config.pdf_parser` override. For PDF inputs, `DocProcessorMixin` uses the override when present; every non-PDF input continues to use the existing `PARSER`/`config.parser`. Both defaults and non-PDF routing remain unchanged. On OpenDataLoader failure, the task fails with a structured parser-stage error and operators can explicitly retry after changing the PDF override.

This retains meaningful benchmark comparisons and prevents a partial OpenDataLoader result plus a fallback result from being mixed into one document. A transparent per-file automatic router was rejected because its quality criteria, rollout controls, and provenance model are not yet defined.

### 2. Use the official Python SDK through a controlled page runner, with fast local mode only

The adapter starts a separate Python runner process for each source page. The runner calls only the pinned `opendataloader_pdf.convert()` public API with `pages=<one-based page>` and fixed fast-local options, writes a bounded structured result manifest, and stores JSON plus Markdown in that page's isolated output directory. The parent adapter uses the same collision-avoidance convention as existing parsers, treats JSON as the sole normalization source, and retains Markdown only as a hashed diagnostic artifact; it must never create duplicate blocks.

The adapter must never build a shell command from a filename. It must not set `hybrid`, `hybrid_url`, `content_safety_off`, or other remote/unsafe options. It sets a validated Java heap only in the runner environment, fixes SDK threads to one, applies a document deadline and per-page deadline, and terminates the runner process tree with `taskkill /T /F` on Windows or a process group on Linux containers. A failed page, missing result manifest, ambiguous artifact, or unproven blank page fails closed before persistence. A hybrid service was rejected for the first release because it duplicates Docling dependencies and introduces a second service/model lifecycle.

### 3. Treat parser artifacts as untrusted input and normalize them at one boundary

The adapter converts upstream elements as follows:

- headings, paragraphs, lists, captions, and unsupported semantic types become `text` blocks with zero-based `page_idx`;
- tables become `table` blocks with a normalized textual/Markdown `table_body` and caption when present;
- images become `image` blocks only after their resolved path is proven to remain under the unique parser output directory and cannot escape through a symbolic link; public media URLs are attached through the established helper, and unsafe/missing images degrade to a safe text marker;
- formula content is represented by the existing equation contract when it is usable, otherwise as text rather than being silently discarded.

Every emitted block includes an internal provenance payload with upstream ID, one-based source page, normalized `[left,bottom,right,top]` bounding box, semantic type, and heading depth/`text_level` where present. The adapter records the PDF-point unit, bottom-left origin, and page basis rather than storing an unexplained raw array. An atomic JSON sidecar manifest keeps raw upstream JSON identity, normalized content identity, page coverage, and element provenance durable without changing current retrieval responses. `doc_status.metadata` receives only lightweight parser identity, coverage, and relative artifact references. Sidecars follow retry overwrite, document deletion, knowledge-base deletion, and existing retention lifecycles. Unknown or malformed elements must produce an actionable parse error or an explicit safe text fallback recorded in the manifest.

### 4. Generalize the PDF page-coverage and cache-identity gates

Replace the Docling-name check with a parser capability/property that declares whether its PDF results provide coverage. Both Docling and OpenDataLoader must return a `PageTrackedContent`-compatible manifest with the source page total and mutually exclusive successful/failed/skipped page sets. The adapter obtains the source count from a local PDF reader, but successful process exit alone is not proof that every page succeeded. Implementation begins with a contract spike against the pinned SDK to identify trustworthy page-status/page-marker output, including blank pages. If batch output cannot prove every page, use a validated per-page strategy or stop before production enablement. Any failed/skipped/ambiguous page prevents quality checks, cache writes, `doc_status` success, and ingestion.

The parse cache identity is extended to include the parser's stable cache identity: backend name, pinned package version, output schema version, and behavior-affecting local options. This avoids reusing data generated by a different OpenDataLoader version or mode. The previous parser-only key was rejected because it permits stale or semantically incompatible output after an upgrade.

### 5. Make runtime prerequisites, licensing, and observability first-class

Pin OpenDataLoader PDF to `2.5.0` in a named optional extra with verified artifact hashes and provide an opt-in container build target/path with JRE 17. The default install/image remains free of the new SDK/JRE. `check_installation()` independently verifies the Python package and Java minimum without network access. Dependency changes stay synchronized across `pyproject.toml`, `setup.py`, and `uv.lock` without adding the package to default requirements.

Before any redistributed/on-prem/offline image ships, scan the actual wheel, fat JAR, OS, Python, Maven, npm, and final container into CycloneDX or SPDX SBOMs. Preserve pinned `LICENSE`, `NOTICE`, third-party notices, and corresponding-source references at a stable product path. Reconcile actual components against upstream notices, including the observed veraPDF `1.31.x` POM versus `1.29.x` notice discrepancy; unknown licenses, `NOASSERTION`, or unresolved versions block distribution. This gate covers the new integration only and does not certify unrelated existing dependencies.

Add structured parser events and metrics for selected backend, package version, page count, duration, output blocks, JVM/runtime preflight failure, artifact-validation failure, and resource/timeout failure. Never log document content, raw paths outside existing policy, or credentials. Before production enablement, generate an SBOM and review OpenDataLoader's bundled third-party notices, including MPL-2.0 components, with the product's license owner.

### 6. Preserve existing security controls

OpenDataLoader's safety filters remain enabled, but do not replace the system's own ingestion injection scan, upload authorization, path validation, file locking, status lifecycle, or audit logging. The backend inherits the same permission-checked upload path and the same worker-only execution model. No API endpoint or RBAC behavior changes.

### 7. Make OpenDataLoader images controlled retrieval assets

Legacy OpenDataLoader chunks may contain either `Image Path: <path>` or
`[图片路径：<path>]`, with a full-width or half-width colon. Query compatibility
parses both protocols, but a marker is never authority to read a file. One
shared resolver normalizes and deduplicates candidates, accepts only regular
supported images recorded in a document media manifest or under a registered
ODL artifact root, and rejects traversal, symlink escape, missing files,
unsupported extensions, and paths outside controlled roots. Direct context,
BM25/bigram lookup, and graph expansion all use this resolver. Telemetry contains
only aggregate protocol, candidate, valid, and rejection counts.

New ingestion uses an auditable, document-scoped media contract. Every eligible
ODL image creates a manifest entry containing a controlled relative path,
SHA-256, MIME, page, element ID, caption, and provenance. Multimodal insertion
creates an independent image description/chunk with the English `Image Path:`
retrieval marker, then binds the persisted chunk ID and document ID to an opaque
media ID in a KB-scoped catalog. The catalog is read back before completion is
reported. Eligible image count, valid manifest count, catalog count, and
persisted image-chunk count must agree; otherwise the document reports
`image_media_incomplete` and does not claim `multimodal_processed` completion.
Unsafe or missing media may yield a provenance-backed text fallback, never a
successful image asset.

The catalog is the authorization boundary for new media delivery. API and SSE
payloads expose only opaque media IDs and fixed same-origin URLs; they never
expose a local path or place bearer tokens in URLs. The media endpoint enforces
the existing KB read permission and revalidates catalog ownership, manifest
identity, containment, regular-file state, MIME/extension, and SHA-256 before
serving bytes. A generic raw-path file endpoint is not an ODL delivery path.
Legacy compatibility may be used only when an audited KB/document ownership
mapping exists; otherwise legacy media delivery fails closed.

Recall order is direct context, then local image/BM25/bigram indexes, then
optional graph association. Graph expansion has one total timeout budget,
defaulting to no more than two seconds, and never removes results already found
by earlier stages. Logs record elapsed milliseconds, attempt count, and total
budget without content or paths.

Existing knowledge bases are not rewritten in place. Compatibility is verified
against the existing `odl解析` data first. Permanent ingestion behavior is then
validated by re-ingesting into the isolated `odl解析_图片修复` knowledge base,
retaining the legacy KB, source PDF, and artifacts until a twenty-question image
acceptance comparison has passed and an operator explicitly approves any agent
binding change.

### 8. Preload knowledge-base detail data without false empty states

The knowledge-base list preloads the document summary and knowledge statistics
for a specific authorised KB before navigation. Desktop pointer intent and
keyboard focus may warm the same request, while click waits for the shared
in-flight result for at most six seconds. A newer click supersedes an older one,
so a late response can populate only its own cache entry and cannot navigate to
or render another KB.

Detail prefetch uses explicit KB-scoped API calls rather than the mutable global
`currentKB`. Its in-memory cache is bounded to twenty KBs, expires after thirty
seconds, and is partitioned by an authentication-session generation. Document
rows are never persisted to browser storage. Logout, authentication expiry, KB
deletion, and successful mutations that can change document summaries or stats
invalidate the relevant entries. A marker or cache entry is never treated as an
authorization decision; every network fill still passes the normal RBAC-protected
endpoint.

The detail page binds every display state to the route KB. A fresh cached result
may seed the first render, but an uncached direct URL shows existing skeleton
styles. Documents and stats have independent loading, ready, refreshing, and
error states. Only a successful ready document response with zero rows may show
the true empty state. Refresh failures preserve already rendered data, while an
initial failure produces an explicit retry state. Entity and graph loading stays
asynchronous and does not block document/stat readiness. Abort, request KB, and
generation checks prevent late responses and stale selections from crossing KBs.

## Risks / Trade-offs

- **JVM startup increases latency and memory for individual uploads** -> restrict initial use to an isolated staging deployment/KB, rely on worker/process timeouts and heap caps, record P50/P95 duration and RSS, and consider an explicitly designed batch/service architecture only after measurement.
- **Upstream output filenames or JSON schema can change** -> pin 2.5.0, validate required schema fields, include package/schema identity in the cache, and cover fixtures in contract tests before upgrades.
- **Successful conversion can still hide page-level loss** -> require a generic coverage manifest, reject invalid/partial output, and use real-document golden tests that compare source page counts.
- **Image references can escape the output directory or be missing** -> resolve paths, enforce the output-root containment check, and downgrade invalid images to recorded text rather than dereferencing arbitrary files.
- **Self-published upstream accuracy claims might not match Chinese business documents** -> define promotion on internal golden-corpus results, not upstream benchmarks.
- **Transitive licenses may affect redistributable images** -> make legal/SBOM approval a deployment gate and retain required NOTICE material.
- **Parser choice is environment-level** -> `PDF_PARSER` prevents non-PDF regressions, but the initial canary still requires a dedicated staging environment/working directory; KB allowlists or a per-upload selector are deferred to a separately specified feature.

## Migration Plan

1. Add and test the adapter behind the optional `PDF_PARSER=opendataloader` setting; preserve `PARSER`, all defaults, and existing documents.
2. Build the opt-in development image with JRE 17 and the optional extra, run the real-stack smoke test, and produce the dependency SBOM/license report.
3. Deploy to a non-production/canary worker with conservative timeout, heap, file-size, and concurrency limits. Upload the approved golden corpus into an isolated test knowledge base.
4. Compare coverage, retrieval-ready content, table/image mapping, duration, peak memory, and worker status behavior with Docling/MinerU. Record a go/no-go decision against the acceptance criteria in `tasks.md`.
5. Expand only through an explicit operator configuration change after review. Keep OpenDataLoader output and provenance artifacts according to the existing output-retention policy.

Rollback clears `PDF_PARSER` (or restores its previous value), followed by a worker restart. New PDFs then return to the existing parser while non-PDF behavior never changes. Already ingested OpenDataLoader documents are not automatically converted: if a production rollback requires different content, operators identify affected documents, retain source/artifacts for diagnosis, delete through the supported workflow, and re-ingest with the previous parser. The initial isolated canary avoids mutating production knowledge bases.

## Open Questions

- Does the pinned SDK expose trustworthy explicit per-page completion, including blank pages? If not, confirm the acceptable per-page validation strategy before the adapter can leave the proof-of-concept stage.
- What production file-size, page-count, Java heap, and worker-timeout limits best fit the deployment hardware? Establish conservative canary defaults before enabling the backend.
- Which internal PDFs may be retained as anonymized automated golden fixtures, and which must remain in a secured external evaluation corpus?
- Does the organization approve distribution of the pinned wheel/JAR and its third-party notices in the production image after SBOM review?
- Should a future citation capability persist parser element provenance into chunk metadata and expose coordinate links in the frontend, rather than reading the sidecar manifest?
