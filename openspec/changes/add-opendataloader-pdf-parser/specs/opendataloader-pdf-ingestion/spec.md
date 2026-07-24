## ADDED Requirements

### Requirement: OpenDataLoader is an explicit PDF-only parser override
The system SHALL expose `opendataloader` as a built-in parser name selected only through an optional PDF-specific parser configuration. The global parser, default parser, and non-PDF routing SHALL remain unchanged, and the backend SHALL process PDF inputs only.

#### Scenario: Default deployment behavior is unchanged
- **WHEN** no parser override is configured
- **THEN** the system SHALL continue to use its existing default parser and SHALL NOT invoke OpenDataLoader.

#### Scenario: Operator explicitly selects OpenDataLoader for a PDF
- **WHEN** a worker is configured with `PDF_PARSER=opendataloader` and receives a PDF
- **THEN** the document processor SHALL invoke `OpenDataLoaderParser.parse_pdf()` through the existing parser interface.

#### Scenario: Non-PDF input retains existing parser behavior
- **WHEN** `PDF_PARSER=opendataloader` is set and the worker receives an Office document or image
- **THEN** the document processor SHALL use the existing global parser and routing behavior and SHALL NOT invoke OpenDataLoader.

#### Scenario: Adapter is directly asked to parse a non-PDF
- **WHEN** `OpenDataLoaderParser` directly receives a non-PDF path
- **THEN** the adapter SHALL return an explicit unsupported-type error.

### Requirement: The backend validates its local runtime before parsing
The OpenDataLoader parser SHALL verify the pinned optional Python package and a Java runtime meeting the configured minimum before it accepts work. The opt-in OpenDataLoader container build SHALL include JRE 17 or a compatible supported runtime; the default installation and image SHALL NOT be required to include either dependency.

#### Scenario: Java runtime is unavailable
- **WHEN** the selected backend cannot locate a compatible Java runtime
- **THEN** `check_installation()` and the parse failure SHALL identify Java as the missing prerequisite with a remediation-oriented message.

#### Scenario: Required local runtime is available
- **WHEN** the pinned Python package and a compatible Java runtime are installed
- **THEN** the backend SHALL pass its installation check without making a network request.

#### Scenario: Optional backend is not installed
- **WHEN** the default installation imports `raganything.parser` without the OpenDataLoader extra or Java
- **THEN** parser discovery SHALL remain usable for existing backends and SHALL NOT fail at module import time.

### Requirement: Conversion runs only in the controlled worker path
The backend SHALL invoke the official local SDK only from the existing document-processing worker path. It SHALL use fast local mode, keep upstream content-safety filters enabled, and SHALL NOT start hybrid mode, configure a remote hybrid URL, or disable upstream safety filtering.

#### Scenario: PDF processing is queued
- **WHEN** an authorized upload is accepted for OpenDataLoader parsing
- **THEN** the FastAPI request path SHALL return the established queued-task response and the JVM conversion SHALL execute in the background worker rather than in the request handler.

#### Scenario: Conversion exceeds a configured operational limit
- **WHEN** parser execution reaches a configured worker timeout or transient runtime resource limit
- **THEN** the worker SHALL mark the upload as a retryable parser-stage failure, record the bounded failure reason, and SHALL NOT insert partial content.
- **AND** the worker SHALL terminate the converter process tree on supported Windows and container deployments.

#### Scenario: Input exceeds a configured hard limit
- **WHEN** PDF byte size or page count exceeds a configured hard limit before conversion
- **THEN** the worker SHALL fail the upload as a non-retryable validation error unless operator configuration changes and SHALL NOT start the converter.

### Requirement: Parser artifacts are isolated and validated before ingestion
For each source PDF, the backend SHALL write artifacts into a unique output directory, use JSON as the sole normalization source, retain page-marked Markdown for diagnostics only, and read only artifacts resolved beneath that directory without symlink escape. It SHALL reject malformed, missing, or ambiguous artifacts before cache or storage writes, and diagnostic Markdown SHALL NOT create duplicate content blocks.

#### Scenario: Valid conversion artifacts are produced
- **WHEN** a local conversion completes successfully with a valid JSON artifact
- **THEN** the backend SHALL normalize its contents and make the validated output available to the document processor.

#### Scenario: Generated image path escapes the parser output directory
- **WHEN** an upstream image reference resolves outside the unique parser output directory
- **THEN** the backend SHALL NOT read the referenced path, SHALL record the rejected reference in provenance, and SHALL emit only a safe text fallback for that element.

#### Scenario: Artifact validation fails
- **WHEN** the converter exits successfully but its expected JSON artifact is missing or cannot be parsed
- **THEN** the backend SHALL fail the parse before cache or knowledge-base insertion and the upload task SHALL expose a parser-stage error.

### Requirement: OpenDataLoader output conforms to the normalized content contract
The backend SHALL map valid OpenDataLoader elements into the existing normalized content-list types with zero-based `page_idx`. Textual elements SHALL become text blocks with heading depth mapped to `text_level` when available, tables SHALL include normalized table content, valid images SHALL include a verified local media path and established public-media URL mapping, and usable formulas SHALL use the existing equation representation. Unsupported elements SHALL be represented by an explicit safe text fallback or cause an actionable validation error; they SHALL NOT be silently discarded.

#### Scenario: Structured textual element is normalized
- **WHEN** OpenDataLoader emits a heading or paragraph with source page number 3
- **THEN** the adapter SHALL emit a `text` block with `page_idx: 2` and its normalized text content.

#### Scenario: Table element is normalized
- **WHEN** OpenDataLoader emits a table element
- **THEN** the adapter SHALL emit a `table` block with normalized table content and the correct zero-based page index.

#### Scenario: Unsupported element is encountered
- **WHEN** OpenDataLoader emits an element type that the adapter does not yet support
- **THEN** the adapter SHALL retain a recorded, safe text fallback or fail with an actionable validation error instead of silently omitting the element.

### Requirement: PDF page coverage is a generic ingestion gate
The document processor SHALL require a complete, non-overlapping page-coverage manifest from every parser that declares PDF coverage support, including Docling and OpenDataLoader. A result with failed, skipped, missing, or ambiguous source pages SHALL not be cached or inserted.

#### Scenario: OpenDataLoader reports complete coverage
- **WHEN** a source PDF has N pages, conversion succeeds, and validated artifacts account for all N pages
- **THEN** the parser result SHALL carry a coverage manifest with `source_total_pages: N` and all pages marked successful before ingestion proceeds.

#### Scenario: Page coverage is incomplete
- **WHEN** an OpenDataLoader result has a failed, skipped, missing, or overlapping page state
- **THEN** the document processor SHALL reject the result before parse-cache persistence and knowledge-base insertion.

#### Scenario: Converter exits successfully without trustworthy page status
- **WHEN** the conversion process exits successfully but its artifacts do not explicitly prove completion for every source page, including blank pages
- **THEN** the document processor SHALL treat coverage as incomplete and SHALL NOT infer success from the process exit code alone.

#### Scenario: A blank page is processed through the page runner
- **WHEN** the adapter requests one source page through the official SDK `pages` option and the runner returns a valid, contained empty JSON artifact for that exact request
- **THEN** the adapter SHALL record that page in `blank_pages`; it SHALL NOT classify any page as blank merely because a batch artifact omitted elements.

### Requirement: Parser provenance is retained with the parsed output
For every normalized OpenDataLoader element, the system SHALL retain upstream element ID when present, original source-page number, semantic type, normalized `[left,bottom,right,top]` bounding box, and heading depth when present in an atomically written provenance sidecar manifest beneath the parser output directory. Bounding-box metadata SHALL state PDF-point units, bottom-left origin, coordinate order, and page basis. The manifest SHALL not contain credentials or unrelated local paths, and `doc_status.metadata` SHALL contain only lightweight parser identity, coverage, and relative artifact references.

#### Scenario: Element has source coordinates
- **WHEN** a normalized element includes an OpenDataLoader bounding box
- **THEN** the provenance manifest SHALL retain that bounding box together with the element's source page and stable parser-element reference.

#### Scenario: Parser output is cached or reused
- **WHEN** parsed OpenDataLoader output is cached or reused
- **THEN** the cache metadata SHALL retain enough parser-output identity to locate the matching provenance manifest without exposing it as a new public retrieval API.

### Requirement: Cache identity changes when backend semantics change
The document parse-cache key SHALL include a stable parser identity for OpenDataLoader: backend name, pinned package version, output-schema version, and behavior-affecting local options. A cache entry generated under a different identity SHALL not be reused.

#### Scenario: Package version changes
- **WHEN** the installed OpenDataLoader package version differs from the version recorded for a cached parse result
- **THEN** the document processor SHALL perform a new parse rather than reuse the cached content.

#### Scenario: Same backend identity is reused
- **WHEN** the source file, parser identity, and parse settings are unchanged
- **THEN** the document processor SHALL remain eligible to reuse its validated cached result.

### Requirement: Redistributed artifacts pass an integration-specific supply-chain gate
Before an OpenDataLoader-enabled wheel, JAR, on-prem/offline bundle, or container is distributed, the system release process SHALL generate an SBOM from the actual final artifacts, preserve required notices and corresponding-source references, and reconcile package versions and licenses. Unknown licenses, `NOASSERTION`, unresolved version mismatches, or missing notices SHALL block distribution. This gate SHALL be described as covering the new OpenDataLoader integration only, not as certification of all existing product dependencies.

#### Scenario: Final artifact has a resolved dependency inventory
- **WHEN** the opt-in image is proposed for distribution
- **THEN** the release evidence SHALL include pinned artifact hashes, final image digest, CycloneDX or SPDX SBOM, retained notice/license resources, and an approved reconciliation record for the actual bundled components.

#### Scenario: Upstream notice differs from the actual dependency graph
- **WHEN** an actual Maven/Python/container component version differs from an upstream third-party notice or has unresolved licensing
- **THEN** distribution SHALL be blocked until the discrepancy is reconciled and formally accepted by the responsible license owner.

### Requirement: Existing ingestion security and observability remain effective
OpenDataLoader-derived text SHALL pass through the existing ingestion injection scan and all established upload authorization, file-lock, status, and audit controls. The system SHALL emit structured parser telemetry without logging source document content or credentials.

#### Scenario: Parsed document contains an injection pattern
- **WHEN** normalized OpenDataLoader text reaches ingestion and matches an existing document-injection rule
- **THEN** the established injection-defense behavior SHALL flag the content and record the security event.

#### Scenario: Parser run completes or fails
- **WHEN** an OpenDataLoader parser run reaches a terminal state
- **THEN** structured telemetry SHALL record backend identity, package version, page count when known, duration, block count when known, and outcome category without recording document text.
