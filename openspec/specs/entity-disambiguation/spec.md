## ADDED Requirements

### Requirement: Entity matching uses token-overlap weighting
The graph entity matching function (`GraphRetriever._match_entities()`) SHALL score entities based on the number of overlapping tokens between query tokens and entity name tokens, rather than simple substring presence. Entities with higher token overlap (i.e., more specific matches) SHALL rank higher than entities with lower overlap.

#### Scenario: Query with specific entity name
- **WHEN** the query is "毕业设计答辩地点是哪里" and the knowledge graph contains entities "毕业设计答辩" (4-token match) and "开题答辩" (1-token match via "答辩")
- **THEN** "毕业设计答辩" SHALL receive a higher match score than "开题答辩"

#### Scenario: Query with only overlapping keyword
- **WHEN** the query is "答辩相关安排" and the knowledge graph contains entities "毕业设计答辩" and "开题答辩" (both match "答辩")
- **THEN** both entities SHALL receive equal scores (both match 1 query token "答辩")

### Requirement: Retrieved chunks annotated with source entity
Chunks retrieved through the graph retrieval channel SHALL include annotation of which entity they were reached through. When multiple entities lead to the same chunk, all source entity names SHALL be listed.

#### Scenario: Single entity source annotation
- **WHEN** a chunk is retrieved via graph traversal starting from entity "毕业设计答辩"
- **THEN** the chunk in the retrieval context SHALL be annotated with `来源实体: 毕业设计答辩`

#### Scenario: Multi-entity source annotation
- **WHEN** a chunk is retrieved via graph traversal from both "毕业设计答辩" and "开题答辩" entities
- **THEN** the chunk SHALL be annotated with both source entity names

### Requirement: RAG prompt includes entity disambiguation instruction
The RAG query system prompt SHALL instruct the LLM to distinguish between similar entities in the retrieval context, to associate facts with specific entity names, and SHALL NOT conflate properties of different entities.

#### Scenario: LLM receives context with multiple similar entities
- **WHEN** the retrieval context contains chunks annotated with different source entities (e.g., "毕业设计答辩" and "开题答辩") that have different attribute values (e.g., different locations)
- **THEN** the LLM SHALL report the attribute value associated with the specific entity mentioned in the user's question, not the other entity

#### Scenario: LLM distinguishes similar entities
- **WHEN** the user asks "毕业设计答辩地点在哪里" and the context contains both "毕业设计答辩→地点13216" and "开题答辩→地点13220"
- **THEN** the LLM SHALL answer "13216" and SHALL NOT answer "13220"
