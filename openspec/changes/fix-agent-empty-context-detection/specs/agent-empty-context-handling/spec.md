## ADDED Requirements

### Requirement: Agent query detects empty retrieval context

The system SHALL detect when `aquery(only_need_context=True)` returns LightRAG's fail_response (containing `"[no-context]"` marker) or when the retrieved context contains no substantive text chunks.

#### Scenario: Retrieval returns fail_response

- **WHEN** a user sends a query via `POST /api/agents/{agent_id}/query/stream` with `agent_mode=none`
- **AND** the knowledge base retrieval returns zero entities, zero relations, and zero vector chunks
- **AND** `aquery(only_need_context=True)` returns LightRAG's fail_response string containing `"[no-context]"`
- **THEN** the system SHALL detect the empty context via the `"[no-context]"` marker
- **AND** the system SHALL NOT emit `📋 检索到 N 字符上下文` with the fail_response length
- **AND** the system SHALL NOT pass the fail_response as retrieval context to the LLM

#### Scenario: Retrieval returns context without text chunks

- **WHEN** a user sends a query with `agent_mode=none`
- **AND** the retrieval returns entity/relation data but no text chunks (no `"[来源 "` markers and context length ≤ 200)
- **THEN** the system SHALL detect the degraded context
- **AND** the system SHALL emit the warning log `agent_query_stream: context has no text chunks.`

### Requirement: Agent query falls back to bypass mode on empty context

The system SHALL fall back to bypass mode when the retrieval context is empty or is a LightRAG fail_response, informing the user clearly.

#### Scenario: Fallback to bypass mode on fail_response

- **WHEN** the system detects fail_response in the retrieval context
- **THEN** the system SHALL switch to bypass mode (`agent_mode="bypass"`)
- **AND** the system SHALL emit a thinking event stating "知识库中暂无相关数据，使用自身知识回答"
- **AND** the system SHALL instruct the LLM to answer using its own knowledge with a disclaimer about data limitations
- **AND** the system SHALL emit a `done` event with `fallback: true`

#### Scenario: Normal retrieval continues without fallback

- **WHEN** retrieval returns valid context containing `"[来源 "` markers or length > 200
- **THEN** the system SHALL proceed with normal RAG prompt assembly (existing behavior)
- **AND** the system SHALL NOT trigger the fallback thinking message
