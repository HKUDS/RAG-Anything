## ADDED Requirements

### Requirement: Query endpoints use three-tier image discovery

The `/query` (non-streaming) and `/query/stream` (streaming) endpoints SHALL use the same three-tier image discovery architecture as the agent endpoints: direct extraction from retrieval context, entity graph traversal, and bigram-scored full-scan fallback.

#### Scenario: /query endpoint discovers images via entity graph

- **WHEN** a user queries `/query` and the retrieval context contains no direct image paths
- **AND** the knowledge graph contains text entities connected via `belongs_to` to image entities matching the query
- **THEN** the endpoint SHALL discover related images via `_discover_images_via_graph()`
- **AND** SHALL enrich the context with backfill text from graph-discovered chunks

#### Scenario: /query endpoint falls back to bigram scan

- **WHEN** graph discovery returns no images for a `/query` request
- **THEN** the endpoint SHALL perform a bigram-scored full-scan of all chunks
- **AND** SHALL only return images with positive bigram scores, sorted by relevance

#### Scenario: /query/stream endpoint uses three-tier discovery

- **WHEN** a user queries `/query/stream` and direct context extraction finds no images
- **THEN** the endpoint SHALL execute graph-based image discovery
- **AND** if graph discovery also returns empty, SHALL execute bigram-scored full-scan

#### Scenario: Image count limit is consistent across endpoints

- **WHEN** any endpoint (agent, /query, /query/stream) discovers images
- **THEN** the returned image list SHALL be capped at 3 images

### Requirement: Image discovery functions are shared across router modules

The image discovery helper functions SHALL be defined in `shared.py` and imported by both `agent.py` and `query.py`, eliminating code duplication.

#### Scenario: _discover_images_via_graph is importable from shared

- **WHEN** `query.py` imports `_discover_images_via_graph` from `shared`
- **THEN** the import SHALL resolve successfully at module load time
- **AND** agent.py SHALL import the same function from shared rather than defining it locally

#### Scenario: _build_backfill_context is importable from shared

- **WHEN** any router module imports `_build_backfill_context` from `shared`
- **THEN** the import SHALL resolve successfully
