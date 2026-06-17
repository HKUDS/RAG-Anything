## ADDED Requirements

### Requirement: Retriever supports in-memory vector search
The Retriever executor SHALL detect whether upstream nodes have provided vector embeddings and text chunks.
When both vectors and chunks are available from upstream, the Retriever SHALL perform in-memory cosine similarity search
instead of querying the persistent LightRAG knowledge base.

#### Scenario: In-memory retrieval when embedding node provides vectors
- **WHEN** an upstream Embedding node outputs a `vector` field and an upstream TextSplitter node outputs a `chunks` field
- **THEN** the Retriever SHALL compute cosine similarity between the query vector and each chunk vector, and return Top-K results

#### Scenario: Fallback to knowledge base when no upstream vectors
- **WHEN** no upstream node provides vector embeddings
- **THEN** the Retriever SHALL fall back to querying the persistent LightRAG knowledge base via `aquery`

### Requirement: Retriever accepts manual query text input
The Retriever node configuration SHALL support an optional `query_text` field.
When `query_text` is provided, it SHALL be used as the retrieval query.
When `query_text` is empty, the Retriever SHALL extract query text from upstream node outputs.

#### Scenario: Manual query text takes priority
- **WHEN** the Retriever node config contains a non-empty `query_text` value
- **THEN** the Retriever SHALL use `query_text` as the search query, ignoring upstream text content

#### Scenario: Auto-extract query from upstream when no manual input
- **WHEN** `query_text` is empty or not configured
- **THEN** the Retriever SHALL extract query text from upstream node outputs via `_extract_text`

### Requirement: Retriever reports search mode in results
The Retriever executor SHALL include a `search_mode` field in its output indicating whether the retrieval used `"in_memory"` or `"knowledge_base"` mode.

#### Scenario: Search mode reported in output
- **WHEN** the Retriever completes retrieval
- **THEN** the output SHALL contain a `search_mode` field with value `"in_memory"` or `"knowledge_base"`

### Requirement: Cosine similarity computation
The system SHALL implement cosine similarity computation using numpy operations.
The computation SHALL normalize query and chunk vectors to unit length, compute dot products, and return the top-K chunk indices sorted by descending similarity.

#### Scenario: Top-K similar chunks returned
- **WHEN** a query vector and a list of chunk vectors are provided with top_k=5
- **THEN** the system SHALL return exactly 5 results (or fewer if fewer chunks exist), sorted by descending cosine similarity score
