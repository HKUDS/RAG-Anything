# Graph Image Discovery

## Purpose

Enable mode-agnostic, semantic-level image discovery during agent Q&A by traversing the entity knowledge graph. When the retrieval context (ctx) contains no image chunks, the system uses entity graph traversal — following `belongs_to` edges from query-matched text entities to image entities — to find related document images. This bridges the gap between Chinese queries and English VLM-generated image descriptions, and works equally for all query modes (rrf, graph, hybrid, local, global, naive, mix) and AgenticRAG paths (ReAct, CoT).

## Requirements

### Requirement: Graph-based image discovery for all query modes

The system SHALL discover document images related to a user query by traversing the entity knowledge graph, independent of the retrieval mode used.

The graph-based discovery SHALL:
- Execute only when `extract_image_paths(ctx)` returns no images from the retrieval context
- Match query tokens against entity names in the knowledge graph via jieba token-overlap scoring
- Traverse `belongs_to` edges from matched text entities to reach image entities (entity_type "image")
- Extract image paths from the source chunks of discovered image entities
- Return at most 5 image paths, deduplicated
- If matched entities count is 0, retry up to 2 times with 1-second intervals to tolerate asynchronous graph construction after document upload

#### Scenario: Chinese query finds English-described chart via entity graph

- **WHEN** user queries "数据库是怎么连接的" and the RRF retrieval context contains no image chunks in top-15
- **AND** the knowledge graph contains a text entity "MySQL" connected via `belongs_to` to an image entity "系统架构图 (image)"
- **AND** the image entity's source chunk contains `Image Path: /output/images/figure_12_1.jpg`
- **THEN** graph-based discovery SHALL return the image path `/output/images/figure_12_1.jpg`

#### Scenario: No related images in knowledge graph

- **WHEN** graph traversal finds no image entities connected to query-matched entities
- **THEN** graph-based discovery SHALL return an empty list, allowing the bigram fallback to execute

#### Scenario: Graph unavailable gracefully degrades

- **WHEN** the HybridSearchEngine or GraphRetriever is not initialized
- **THEN** graph-based discovery SHALL return an empty list without raising an exception

#### Scenario: Retry on zero matched entities

- **WHEN** graph entity matching returns 0 entities on first attempt
- **THEN** graph-based discovery SHALL retry matching up to 2 more times with 1-second intervals
- **AND** if all retries return 0 entities, SHALL return an empty list

### Requirement: Text backfill from graph-discovered image chunks

When graph-based discovery finds image-related chunks, the system SHALL append the text content of those chunks to the LLM context to improve answer quality.

The backfill SHALL:
- Include at most 5 chunks, each truncated to 1500 characters
- Skip chunks whose content already appears in the retrieval context (matched by first 80 characters)
- Annotate each backfilled chunk with `[来源 <document_name>（图谱关联）]` marker, where `<document_name>` is resolved from the `ScoredChunk.document_name` or `ScoredChunk.file_path` attribute (NOT defaulting to "未知文档" when the information is available)

#### Scenario: Backfill enriches LLM context

- **WHEN** graph-based discovery finds 3 image-related chunks not present in the original retrieval context
- **THEN** the system SHALL append their text content to `ctx` before sending to the LLM
- **AND** each chunk SHALL be prefixed with a source marker containing the document name and "图谱关联" label

#### Scenario: Backfill deduplicates against existing context

- **WHEN** a graph-discovered chunk has the same first 80 characters as a chunk already in the retrieval context
- **THEN** that chunk SHALL be excluded from backfill

### Requirement: Image discovery applies to AgenticRAG paths

The graph-based image discovery SHALL also execute for AgenticRAG query paths (ReAct and CoT modes). When bigram fallback executes in the AgenticRAG path, the `scored_texts` collection SHALL only include chunks with a positive bigram score (score > 0), matching the behavior of the normal RAG path.

#### Scenario: ReAct agent query triggers graph image discovery

- **WHEN** agent_mode is "react" and the trace observations contain no image paths
- **THEN** graph-based discovery SHALL execute on the combined search observations text
- **AND** discovered images SHALL be included in the query history record

#### Scenario: CoT agent query triggers graph image discovery

- **WHEN** agent_mode is "cot" and the cot_context contains no image paths
- **THEN** graph-based discovery SHALL execute on the combined cot_context and query text
- **AND** discovered images SHALL be included in the query history record

#### Scenario: Bigram text collection only includes positive scores

- **WHEN** bigram fallback executes in the AgenticRAG path and some chunks have score 0
- **THEN** those score-0 chunks SHALL NOT be included in `scored_texts` for backfill

### Requirement: ScoredChunk carries document source information during graph retrieval

When `GraphRetriever.search_with_paths()` constructs `ScoredChunk` objects, it SHALL populate the `document_name` and `file_path` attributes from the underlying chunk data in `text_chunks` storage.

#### Scenario: ScoredChunk has document name

- **WHEN** `search_with_paths()` retrieves a chunk from `text_chunks` storage that has a `document_name` field
- **THEN** the returned `ScoredChunk.document_name` SHALL equal the stored value

#### Scenario: ScoredChunk falls back to file_path

- **WHEN** a chunk has `file_path` but no `document_name`
- **THEN** the returned `ScoredChunk.file_path` SHALL equal the stored value
