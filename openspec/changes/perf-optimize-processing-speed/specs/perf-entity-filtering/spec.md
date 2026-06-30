# perf-entity-filtering

Post-extraction entity filtering by minimum graph degree to reduce noise and speed up the merge phase.

## ADDED Requirements

### Requirement: Filter entities by minimum graph degree

The system SHALL respect the `ENTITY_EXTRACTION_MIN_DEGREE` environment variable to remove entities whose graph degree (number of connected relations) is below the configured threshold after extraction and merge.

#### Scenario: Default filtering with MIN_DEGREE=1
- **WHEN** `ENTITY_EXTRACTION_MIN_DEGREE=1` is set in `.env`
- **THEN** after entity extraction and merge completes, entities with 0 relations SHALL be removed from the knowledge graph
- **AND** the filtered entities SHALL NOT appear in graph queries or the knowledge graph visualization

#### Scenario: No filtering with MIN_DEGREE=0
- **WHEN** `ENTITY_EXTRACTION_MIN_DEGREE=0` is set in `.env`
- **THEN** all extracted entities SHALL be retained regardless of their graph degree

#### Scenario: Aggressive filtering with MIN_DEGREE=2
- **WHEN** `ENTITY_EXTRACTION_MIN_DEGREE=2` is set in `.env`
- **THEN** only entities with 2 or more relations SHALL be retained

### Requirement: Entity filtering reduces merge phase overhead

Filtering entities by minimum degree SHALL reduce the number of entities processed in the Phase 1 merge step, proportionally reducing LLM summarization calls.

#### Scenario: Fewer entities to merge
- **WHEN** MIN_DEGREE filtering removes N entities
- **THEN** the merge phase SHALL process fewer entities
- **AND** the LLM summarization call count SHALL decrease proportionally
