## ADDED Requirements

### Requirement: List update timestamps preserve per-KB identity
The knowledge-base list SHALL not report a common update time merely because a
full metadata snapshot was saved while creating or initializing another KB.

#### Scenario: Full metadata snapshot preserves existing KB timestamps
- **WHEN** a new knowledge base is created through a full metadata snapshot save
- **THEN** existing knowledge bases SHALL retain their persisted update times
