## ADDED Requirements

### Requirement: Text entities linked to multimodal chunks at processing time
After multimodal content processing completes, the system SHALL scan all multimodal chunks for mentions of entity names already in the knowledge graph. For each entity name found in a multimodal chunk's content, the system SHALL add the multimodal chunk's ID to the entity's `source_id` list, enabling graph traversal to reach the multimodal chunk from the entity.

#### Scenario: Table chunk contains entity attribute data
- **WHEN** document processing completes and a table chunk contains the text "毕业设计答辩" and "13216", and the knowledge graph already has an entity named "毕业设计答辩" extracted from text
- **THEN** the entity "毕业设计答辩" in the knowledge graph SHALL have the table chunk's ID in its `source_id` list

#### Scenario: Entity name not in multimodal chunk
- **WHEN** a multimodal chunk does not contain any entity name from the knowledge graph
- **THEN** no new links SHALL be created for that chunk

### Requirement: Graph edges connect entities to multimodal chunks
For each new entity-to-chunk link discovered, the system SHALL create a `mentions` edge in the knowledge graph connecting the entity node to the multimodal chunk node, enabling BFS traversal during graph retrieval to discover multimodal chunks.

#### Scenario: Entity BFS reaches multimodal chunk
- **WHEN** graph retrieval performs BFS traversal from entity "毕业设计答辩" with depth >= 1
- **THEN** the traversal SHALL reach the multimodal table chunk that was linked during processing, and include its content in retrieval results

### Requirement: Existing documents reprocessable
Users SHALL be able to re-process existing documents with a flag (e.g., `force_reprocess=true`) to trigger the entity-multimodal linking for previously processed documents.

#### Scenario: Force reprocess triggers relinking
- **WHEN** a user uploads a previously-processed document with `force_reprocess=true`
- **THEN** the document SHALL be re-processed and entity-multimodal links SHALL be created
