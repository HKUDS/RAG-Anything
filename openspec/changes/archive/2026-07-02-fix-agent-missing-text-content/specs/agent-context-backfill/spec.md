## ADDED Requirements

### Requirement: Bigram fallback scanner backfills text content

The system SHALL, when the bigram-based image fallback scanner finds matching image chunks from `kv_store_text_chunks.json`, also extract and inject the text content of those chunks into the retrieval context, ensuring text and image data stay consistent.

#### Scenario: Bigram scanner finds image chunks with text

- **WHEN** a user sends a query via `POST /api/agents/{agent_id}/query/stream` with `agent_mode=none`
- **AND** the retrieved context has no images (`extract_image_paths(ctx)` returns empty)
- **AND** the bigram fallback scanner finds chunks containing matching images in `kv_store_text_chunks.json`
- **THEN** the system SHALL extract the text content from those matched chunks
- **AND** the system SHALL inject the extracted text content into the retrieval context (prepended or appended)
- **AND** the injected text SHALL follow the same `[来源 doc_name]` annotation format as normal retrieval results to enable citation tracking
- **AND** the system SHALL log the number of text chunks backfilled

#### Scenario: Bigram backfilled text eliminates false degraded detection

- **WHEN** bigram backfill injects text content that contains `[来源 ` markers or reaches > 200 characters total
- **THEN** the `_has_chunks` check SHALL evaluate the enriched context (original + backfilled)
- **AND** the `_DEGRADED_HINT` SHALL NOT be injected into the LLM prompt
- **AND** the system SHALL proceed with normal RAG prompt assembly

#### Scenario: Bigram scanner finds no matching chunks

- **WHEN** the bigram fallback scanner finds zero image paths or zero chunks with positive bigram scores
- **THEN** the system SHALL leave the retrieval context unchanged
- **AND** the existing `_has_chunks` / `_is_empty_context` logic SHALL apply without modification

### Requirement: Backfill avoids duplicate content

The system SHALL deduplicate backfilled text against the existing retrieval context to avoid repetitiveness.

#### Scenario: Same chunk appears in both retrieval and backfill

- **WHEN** bigram scanning finds a chunk whose `chunk_id` already exists in the original retrieval context
- **THEN** the system SHALL skip injecting text from that chunk
- **AND** the system SHALL still use the image path from that chunk if not already present in `agent_images`

#### Scenario: Same image path found in multiple chunks

- **WHEN** multiple backfill chunks contain the same image path
- **THEN** the system SHALL deduplicate image paths (keep highest-score occurrence)
- **AND** the system SHALL merge text content from all unique chunks containing that image

### Requirement: Backfill respects token budget

The system SHALL limit backfilled text content to avoid exceeding the LLM context window.

#### Scenario: Backfill would exceed token budget

- **WHEN** the total context length after backfill would exceed the configured `max_total_tokens` (default 16000 characters)
- **THEN** the system SHALL truncate backfilled chunks to fit within the budget
- **AND** the system SHALL prioritize higher bigram-score chunks for inclusion
- **AND** the system SHALL log a warning about truncated backfill
