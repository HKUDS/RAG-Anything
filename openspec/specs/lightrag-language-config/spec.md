## ADDED Requirements

### Requirement: LightRAG language is configurable

The system SHALL inject a `language` parameter into LightRAG's `addon_params` during instance initialization, defaulting to `"Chinese"`.

#### Scenario: Chinese knowledge base uses Chinese keyword extraction

- **WHEN** a LightRAG instance is initialized for a knowledge base
- **AND** the `LIGHTRAG_LANGUAGE` environment variable is not set
- **THEN** the system SHALL set `addon_params.language = "Chinese"`
- **AND** LightRAG's keyword extraction SHALL extract Chinese keywords from Chinese queries
- **AND** extracted keywords SHALL match Chinese-named entities in the vector database

#### Scenario: Language can be overridden via environment variable

- **WHEN** a LightRAG instance is initialized
- **AND** `LIGHTRAG_LANGUAGE=English` is set in the environment
- **THEN** the system SHALL set `addon_params.language = "English"`
- **AND** LightRAG SHALL extract English keywords from English queries

### Requirement: Hybrid query mode returns results for Chinese queries

The system SHALL NOT return zero results when querying a Chinese knowledge base with `mode="hybrid"` via LightRAG's built-in query.

#### Scenario: Hybrid query on Chinese KB returns matching entities

- **WHEN** a user sends a Chinese query (e.g., "系统包含哪些功能模块") via `agent_mode=none`, `query_mode=hybrid`
- **AND** the knowledge base contains Chinese-named entities matching the query concepts
- **THEN** LightRAG's hybrid query SHALL return at least 3 matching entities
- **AND** the result SHALL NOT be `"[no-context]"` fail_response
