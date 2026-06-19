## MODIFIED Requirements

### Requirement: Agent query detects empty retrieval context

The system SHALL detect when `aquery(only_need_context=True)` returns LightRAG's fail_response (containing `"[no-context]"` marker) or when the retrieved context contains no substantive text chunks AFTER bigram backfill has been applied.

#### Scenario: Retrieval returns fail_response

- **WHEN** a user sends a query via `POST /api/agents/{agent_id}/query/stream` with `agent_mode=none`
- **AND** the knowledge base retrieval returns zero entities, zero relations, and zero vector chunks
- **AND** `aquery(only_need_context=True)` returns LightRAG's fail_response string containing `"[no-context]"`
- **THEN** the system SHALL detect the empty context via the `"[no-context]"` marker
- **AND** the system SHALL NOT emit `📋 检索到 N 字符上下文` with the fail_response length
- **AND** the system SHALL NOT pass the fail_response as retrieval context to the LLM
- **AND** the system SHALL NOT run the bigram image fallback scanner (no valid context to scan)

#### Scenario: Retrieval returns context without text chunks (degraded)

- **WHEN** a user sends a query with `agent_mode=none`
- **AND** the retrieval returns entity/relation data but no text chunks (no `"[来源 "` markers and context length ≤ 200)
- **AND** bigram backfill does NOT add sufficient text to reach `_has_chunks` threshold
- **THEN** the system SHALL detect the degraded context
- **AND** the system SHALL emit the warning log `agent_query_stream: context has no text chunks.`

#### Scenario: Degraded context enriched by bigram backfill

- **WHEN** a user sends a query with `agent_mode=none`
- **AND** the retrieval returns entity/relation data with no text chunks (no `"[来源 "` markers and context length ≤ 200)
- **AND** bigram backfill successfully injects text content that brings context above 200 characters
- **THEN** the `_has_chunks` evaluation SHALL return True for the enriched context
- **AND** the system SHALL NOT emit the degraded context warning
- **AND** the `_DEGRADED_HINT` SHALL NOT be injected into the LLM prompt
- **AND** the system SHALL proceed with normal RAG prompt assembly using the enriched context

### Requirement: Agent query falls back to bypass mode on empty context

The system SHALL fall back to bypass mode when the retrieval context is empty or is a LightRAG fail_response (unchanged from previous version). The fallback determination SHALL occur AFTER bigram backfill has been attempted, ensuring that backfilled content can prevent unnecessary fallbacks.

#### Scenario: Fallback to bypass mode on fail_response

- **WHEN** the system detects fail_response in the retrieval context
- **THEN** the system SHALL emit a thinking event stating "知识库中暂无相关数据"
- **AND** the system SHALL return the fallback message "抱歉，知识库中暂无与您问题相关的数据，无法回答此问题。请尝试上传相关文档或换个问题。"
- **AND** the system SHALL emit a `done` event with `fallback: true` and `images: []`
- **AND** the system SHALL NOT proceed to LLM inference

#### Scenario: Normal retrieval continues without fallback

- **WHEN** retrieval returns valid context containing `"[来源 "` markers or length > 200
- **OR** bigram backfill enriches the context to contain `"[来源 "` markers or reach length > 200
- **THEN** the system SHALL proceed with normal RAG prompt assembly (existing behavior)
- **AND** the system SHALL NOT trigger the fallback thinking message
- **AND** images found via extraction or bigram scanning SHALL be included in the response

## ADDED Requirements

### Requirement: Empty context detection accounts for backfill results

The `_is_empty_context()` function SHALL NOT be called with the original raw context when bigram backfill has added text content. Instead, the enriched context SHALL be used for the emptiness check.

#### Scenario: Raw context is empty but backfill adds content

- **WHEN** the original RRF context passes `_is_empty_context()` (returns True)
- **AND** bigram backfill successfully finds and injects text from matching chunks
- **THEN** the system SHALL re-evaluate emptiness against the enriched context
- **AND** if the enriched context passes the check, the system SHALL proceed with normal processing
- **AND** the `is_fallback` flag SHALL be set to False in query history records
