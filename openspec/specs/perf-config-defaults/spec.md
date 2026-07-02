# perf-config-defaults

Optimized concurrency and chunking defaults for faster document processing.

## ADDED Requirements

### Requirement: Configurable LLM concurrency via MAX_ASYNC

The system SHALL respect the `MAX_ASYNC` environment variable to control LightRAG's `llm_model_max_async` parameter, which governs the number of concurrent LLM calls during entity/relation extraction and merge phases.

#### Scenario: User sets MAX_ASYNC in .env
- **WHEN** `MAX_ASYNC=12` is set in `.env`
- **THEN** the worker subprocess SHALL initialize LightRAG with `llm_model_max_async=12`
- **AND** the merge phase graph_max_async SHALL be 24 (MAX_ASYNC × 2)

#### Scenario: MAX_ASYNC not set (default)
- **WHEN** `MAX_ASYNC` is not present in the environment
- **THEN** the worker SHALL use the code default of 4 as the safe floor value

### Requirement: Configurable chunk size via CHUNK_SIZE

The system SHALL respect the `CHUNK_SIZE` environment variable to control the token size of text chunks passed to LightRAG's entity extraction.

#### Scenario: User sets CHUNK_SIZE in .env
- **WHEN** `CHUNK_SIZE=1400` is set in `.env`
- **THEN** the worker SHALL initialize LightRAG with `chunk_token_size=1400`
- **AND** documents SHALL be split into fewer, larger chunks compared to the default of 800

#### Scenario: CHUNK_SIZE exceeds maximum
- **WHEN** `CHUNK_SIZE=5000` is set in `.env`
- **THEN** the value SHALL be clamped to the maximum of 4096

### Requirement: Configurable entity extraction concurrency via ENTITY_EXTRACT_CONCURRENCY

The system SHALL respect the `ENTITY_EXTRACT_CONCURRENCY` environment variable to control `embedding_func_max_async`, which governs the number of concurrent embedding calls.

#### Scenario: User sets ENTITY_EXTRACT_CONCURRENCY in .env
- **WHEN** `ENTITY_EXTRACT_CONCURRENCY=6` is set in `.env`
- **THEN** the worker SHALL initialize LightRAG with `embedding_func_max_async=6`

### Requirement: Configurable parallel file processing via MAX_CONCURRENT_FILES

The system SHALL respect the `MAX_CONCURRENT_FILES` environment variable to control how many worker subprocesses can process documents simultaneously.

#### Scenario: User sets MAX_CONCURRENT_FILES
- **WHEN** `MAX_CONCURRENT_FILES=3` is set in `.env`
- **THEN** the upload queue SHALL allow up to 3 concurrent worker subprocesses for the same KB
