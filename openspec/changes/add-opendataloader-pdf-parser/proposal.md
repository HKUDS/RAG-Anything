## Why

The current ingestion stack relies on Docling, MinerU, Marker, and PaddleOCR, but it lacks an optional PDF parser candidate that combines local execution, structured JSON coordinates, and tagged-PDF-aware extraction. OpenDataLoader PDF 2.5.0 may fill that gap for PDF-only workloads, but its quality, resource profile, and redistribution obligations must be proven against this product before adoption.

The integration must be deliberately bounded. The upstream Python SDK starts a JVM and writes artifacts to disk, so treating it as a drop-in replacement would introduce operational and data-integrity risks. A feature-gated parser provides a measurable path to evaluate it against the project's real documents before any broader rollout.

## What Changes

- Add `opendataloader` as an explicitly selected, PDF-only backend through a new optional `PDF_PARSER` override; keep `PARSER`, current defaults, and all non-PDF routing unchanged.
- Add a production-safe adapter that invokes the pinned OpenDataLoader PDF Python SDK only inside the existing background document worker, parses its JSON and Markdown artifacts, and emits the project's normalized content-list contract.
- Preserve upstream page number, bounding box, source element ID, heading depth, and generated-media references in parser provenance sidecar data for future source-location citations.
- Validate the Java runtime, upstream output, source page count, and generated media paths before any parsed content is inserted. Reject malformed, partial, or ambiguous output rather than silently falling back to another parser.
- Add a pinned optional Python extra, an opt-in JRE 17 container variant/build path, non-secret configuration documentation, resource/time limits, structured observability, and an SBOM/license review gate.
- Treat upstream Apache-2.0 core licensing separately from the bundled wheel/JAR/container supply chain. Scan the actual release artifacts and block redistributed/on-prem images on unresolved third-party version or license discrepancies; this review does not certify unrelated existing dependencies.
- Add unit, contract, worker, security, and opt-in real-stack regression coverage, followed by a controlled canary evaluation on representative PDFs.

## Capabilities

### New Capabilities

- `opendataloader-pdf-ingestion`: Safely ingest PDF files through an explicitly selected OpenDataLoader backend while preserving normalized content, page coverage, and parser provenance.

### Modified Capabilities

None.

## Impact

- Parser layer: `raganything/parser/__init__.py`, a new `raganything/parser/opendataloader_parser.py`, `raganything/config.py`, parser initialization, and parser-focused tests.
- Ingestion and worker behavior: `raganything/processor/doc_processor.py`, `process_worker.py`, knowledge-base worker configuration, output/cache handling, and operational metrics.
- Deployment: `pyproject.toml`, `setup.py`, the lockfile, an opt-in `Dockerfile` build path, `env.example`, and deployment documentation. Default images and dependencies remain unchanged unless the backend is explicitly included.
- Security and compliance: the existing ingestion injection scan remains mandatory; OpenDataLoader safety filtering stays enabled; no hybrid server, remote parsing, automatic fallback, or knowledge-base migration is introduced in this change.
