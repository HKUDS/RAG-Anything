## ADDED Requirements

### Requirement: Knowledge Base Search via Tool
The system SHALL provide a SearchTool that allows the LLM to actively query the RAG knowledge base during reasoning, rather than relying solely on the initial retrieval.

#### Scenario: Active knowledge retrieval during reasoning
- **WHEN** the LLM decides it needs more context during a ReAct step
- **THEN** SearchTool.execute(query="...") retrieves relevant documents from the knowledge base and returns them as observation

#### Scenario: Search with specified query mode
- **WHEN** SearchTool is called with query_mode="hybrid"
- **THEN** the system performs hybrid search (dense + sparse) on the knowledge base

#### Scenario: Empty search result
- **WHEN** SearchTool returns no relevant documents for the query
- **THEN** the tool returns "知识库中未找到相关信息" as observation, allowing the LLM to try alternative queries or tools
