## MODIFIED Requirements

### Requirement: /api/query accepts agent_mode parameter
The `server.py` `/api/query` endpoint SHALL accept an optional `agent_mode` parameter ("none" | "react" | "cot"). When set to "react" or "cot", the endpoint SHALL initialize AgenticRAG and execute the reasoning loop.

#### Scenario: Default mode unchanged
- **WHEN** `/api/query` is called without agent_mode
- **THEN** the endpoint SHALL behave exactly as before this change

#### Scenario: ReAct mode activated
- **WHEN** `/api/query` is called with `"agent_mode": "react"`
- **THEN** the endpoint SHALL create AgenticRAG, register enabled tools, execute ReAct loop, and return `{"answer": ..., "reasoning_trace": {...}}`

#### Scenario: CoT mode activated
- **WHEN** `/api/query` is called with `"agent_mode": "cot"`
- **THEN** the endpoint SHALL execute CoT reasoning and return the result with reasoning_trace

### Requirement: Response includes reasoning_trace in agentic mode
When agent_mode is "react" or "cot", the response SHALL include a `reasoning_trace` field.

#### Scenario: Trace included
- **WHEN** an agentic query completes
- **THEN** the response SHALL contain "reasoning_trace" with steps, total_steps, total_elapsed_ms

#### Scenario: Non-agentic response excludes trace
- **WHEN** a query without agent_mode completes
- **THEN** the response SHALL NOT contain "reasoning_trace"
