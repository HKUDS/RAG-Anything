## ADDED Requirements

### Requirement: Knowledge Base Statistics Query
The system SHALL provide a DBQuery tool that allows the LLM to query read-only statistics about knowledge bases (document count, total size, processing status).

#### Scenario: Query document count
- **WHEN** DBQuery is called with query "SELECT COUNT(*) FROM documents WHERE kb_name='default'"
- **THEN** the system returns the document count for the specified knowledge base

#### Scenario: Query processing status
- **WHEN** DBQuery is called with query about pending/processing/completed status
- **THEN** the system returns the count breakdown by processing status

#### Scenario: Invalid SQL blocked
- **WHEN** DBQuery is called with INSERT, UPDATE, DELETE, DROP, or ALTER statements
- **THEN** the system returns "仅允许只读查询 (SELECT)" without executing

#### Scenario: SQL syntax error
- **WHEN** DBQuery is called with malformed SQL
- **THEN** the system returns a descriptive error message without exposing internal schema

### Requirement: Conversation History Query
The system SHALL allow DBQuery to read conversation metadata (thread count, message count, last activity) for analytics purposes.

#### Scenario: Query conversation stats
- **WHEN** DBQuery is called to count conversation threads per agent
- **THEN** the system returns the thread count grouped by agent_id

### Requirement: Database Schema Exposure
The system SHALL expose a limited, read-only schema description to the LLM context so it can formulate valid queries.

#### Scenario: Schema available in tool description
- **WHEN** the LLM receives the DBQuery tool description
- **THEN** the description SHALL include allowed table names, column names, and example queries
