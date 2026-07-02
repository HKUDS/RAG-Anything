## Why

A 40KB Chinese thesis document (36-41 text chunks) takes ~1 hour to process through RAG-Anything's `process_document_complete()` pipeline. The bottleneck is concentrated in the LLM-driven entity/relation merge phase and VLM multimodal processing. With the current default configuration, document processing throughput is too low for production knowledge base ingestion scenarios.

## What Changes

- **Raise default concurrency limits** (`MAX_ASYNC`, `ENTITY_EXTRACT_CONCURRENCY`) to better utilize API capacity
- **Increase default chunk size** (`CHUNK_SIZE`) to reduce the number of LLM extraction calls per document
- **Add `ENTITY_EXTRACTION_MIN_DEGREE`** filtering to remove isolated graph nodes with zero relations
- **Document per-scenario multimodal toggles** so users can disable image/equation VLM processing when not needed
- **Add processing-speed tuning guidance** to `.env` comments and documentation

## Capabilities

### New Capabilities
- `perf-config-defaults`: Optimized concurrency and chunking defaults for faster document processing
- `perf-entity-filtering`: Post-extraction entity filtering by minimum graph degree to reduce noise
- `perf-multimodal-gating`: Documented per-scenario guidance for selectively disabling VLM-heavy multimodal processing

### Modified Capabilities
<!-- No existing specs to modify -->

## Impact

- **`.env` file**: New/modified defaults for `MAX_ASYNC` (7→12), `CHUNK_SIZE` (800→1400), `ENTITY_EXTRACT_CONCURRENCY` (4→6), `ENTITY_EXTRACTION_MIN_DEGREE` (0→1)
- **`process_worker.py`**: No code changes required — all tunables already read from env vars
- **`raganything/config.py`**: No code changes required — defaults from env vars
- **API endpoints**: No changes — transparent to users
- **DashScope API**: Higher concurrency may increase short-term QPS; within free tier limits at the proposed values
