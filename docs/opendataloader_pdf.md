# OpenDataLoader PDF Backend

`opendataloader` is an opt-in PDF override. It never replaces the global
parser and it does not parse non-PDF files.

Marker is not exposed as a project extra: Marker requires `Pillow<11`, whereas
the default MinerU runtime requires `Pillow>=11`. It must run in a separately
designed worker/container and cannot be combined with MinerU, `all`, or
OpenDataLoader. The old advertised Marker extra is intentionally absent rather
than leaving an install command that cannot resolve.

## Prerequisites

- Install `raganything[opendataloader]`; the dependency is pinned to
  `opendataloader-pdf==2.5.0`.
- Provide Java 17 or newer through `JAVA_HOME` or `PATH`.
- Enable it only in an isolated worker/staging deployment with
  `PDF_PARSER=opendataloader`. Leave `PARSER` set to an existing general
  parser such as `mineru`.

The adapter uses the official Python SDK in a supervised child process once
per PDF page. It uses local fast mode only; hybrid, remote URLs, fallback, and
disabled content-safety options are not supported. A page with missing,
ambiguous, invalid, or out-of-root artifacts fails the whole upload before
cache or ingestion.

## Resource Controls

`ODL_TIMEOUT` limits one document, `ODL_PAGE_TIMEOUT` limits one controlled
runner, `ODL_JAVA_HEAP` accepts only values such as `-Xmx2g`, and
`ODL_CONCURRENCY` defaults to one conversion per worker. `ODL_MAX_PAGES` and
`ODL_MAX_BYTES` reject inputs before Java starts. Timeouts terminate the runner
process tree on Windows and Linux containers.

Parser artifacts and provenance sidecars remain under the parser output root.
They contain relative references and hashes, never a public provenance API or
document text in telemetry. Delete/re-ingest through the supported document or
knowledge-base lifecycle; do not remove individual sidecars manually.

## Isolated Staging Procedure

Use a dedicated worker deployment, `WORKING_DIR`, knowledge base, and storage
namespace. Do not point this parser at a production knowledge base during the
evaluation. Start with `ODL_CONCURRENCY=1` and the SDK thread cap of one, then
set `ODL_MAX_PAGES`, `ODL_MAX_BYTES`, `ODL_JAVA_HEAP`, `ODL_TIMEOUT`, and
`ODL_PAGE_TIMEOUT` from measured staging capacity. These values are deployment
limits, not application defaults.

For a PDF-only canary, leave the general routing unchanged and configure the
worker as follows:

```text
PARSER=mineru
PDF_PARSER=opendataloader
ODL_CONCURRENCY=1
```

Run the approved external corpus in this isolated environment and retain the
coverage, quality, injection-defense, P50/P95, and peak-memory report with the
release evidence. A task failing coverage, preflight, resource, timeout,
conversion, or artifact validation must remain failed; there is no automatic
retry through MinerU, Docling, hybrid, or remote parsing.

## Container

The default image has no Java or OpenDataLoader dependency. Build the opt-in
image with `docker build --target opendataloader -t raganything:opendataloader .`.
It verifies Java and the pinned SDK while building.

## Rollback

Clear or restore `PDF_PARSER`, restart document workers, and new PDFs return to
the global parser. Existing OpenDataLoader documents are unchanged; retain the
source and use supported deletion followed by re-ingestion when rebuilt content
is required.

## Distribution Gate

Before distributing the opt-in wheel, JAR bundle, or image, generate an SBOM
from the actual final artifacts; record wheel/JAR hashes, image digest, notices,
corresponding-source references, and version reconciliation. `NOASSERTION`,
unresolved licenses, missing notices, or the veraPDF notice/version discrepancy
block distribution. This gate covers this integration only and requires written
license-owner approval.

The executable gate is `scripts/opendataloader_release_gate.py`, with generated
notices under `OSS_NOTICES/opendataloader-pdf/` and approval/reconciliation
records under `release-evidence/opendataloader-pdf/`. Templates are deliberately
non-approving and cannot pass the gate.
