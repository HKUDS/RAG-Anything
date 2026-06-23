## ADDED Requirements

### Requirement: Graph-based image discovery for all query modes

The system SHALL discover document images related to a user query by traversing the entity knowledge graph, independent of the retrieval mode used.

The graph-based discovery SHALL:
- Execute only when `extract_image_paths(ctx)` returns no images from the retrieval context
- Match query tokens against entity names in the knowledge graph via jieba token-overlap scoring
- Traverse `belongs_to` edges from matched text entities to reach image entities (entity_type "image")
- Extract image paths from the source chunks of discovered image entities
- Return at most 5 image paths, deduplicated

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

### Requirement: Text backfill from graph-discovered image chunks

When graph-based discovery finds image-related chunks, the system SHALL append the text content of those chunks to the LLM context to improve answer quality.

The backfill SHALL:
- Include at most 5 chunks, each truncated to 1500 characters
- Skip chunks whose content already appears in the retrieval context (matched by first 80 characters)
- Annotate each backfilled chunk with `[来源 文档名（图谱关联）]` marker

#### Scenario: Backfill enriches LLM context

- **WHEN** graph-based discovery finds 3 image-related chunks not present in the original retrieval context
- **THEN** the system SHALL append their text content to `ctx` before sending to the LLM
- **AND** each chunk SHALL be prefixed with a source marker containing the document name and "图谱关联" label

#### Scenario: Backfill deduplicates against existing context

- **WHEN** a graph-discovered chunk has the same first 80 characters as a chunk already in the retrieval context
- **THEN** that chunk SHALL be excluded from backfill

### Requirement: Image discovery applies to AgenticRAG paths

The graph-based image discovery SHALL also execute for AgenticRAG query paths (ReAct and CoT modes).

#### Scenario: ReAct agent query triggers graph image discovery

- **WHEN** agent_mode is "react" and the trace observations contain no image paths
- **THEN** graph-based discovery SHALL execute on the combined search observations text
- **AND** discovered images SHALL be included in the query history record

#### Scenario: CoT agent query triggers graph image discovery

- **WHEN** agent_mode is "cot" and the cot_context contains no image paths
- **THEN** graph-based discovery SHALL execute on the combined cot_context and query text
- **AND** discovered images SHALL be included in the query history record
