## MODIFIED Requirements

### Requirement: Image discovery applies to all query endpoints

The three-tier image discovery architecture (direct extraction → entity graph traversal → bigram-scored full-scan) SHALL execute for ALL query endpoints: agent streaming (`/agent/stream`), non-streaming query (`/query`), and streaming query (`/query/stream`).

The shared implementation SHALL:
- Be defined in `raganything/routers/shared.py` as `_discover_images_via_graph()` and `_build_backfill_context()`
- Be imported by both `agent.py` and `query.py`
- Produce identical image discovery results for the same query and knowledge base regardless of which endpoint is used

#### Scenario: Same query returns same images across endpoints

- **WHEN** the same query is executed against the same knowledge base via `/agent/stream` and `/query`
- **THEN** both endpoints SHALL return the same set of discovered images (modulo async timing)
