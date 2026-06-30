## Context

RAG-Anything processes documents through a multi-stage pipeline: parse → chunk → entity extraction (LLM) → embedding → merge (LLM + VDB + GraphDB) → multimodal processing (VLM) → finalize. A 40KB thesis with 36-41 chunks takes ~1 hour, concentrated in the LLM-driven merge phase and VLM multimodal processing.

**Current defaults** (from `process_worker.py:193-201`):
```
CHUNK_SIZE=800, MAX_ASYNC=4, ENTITY_EXTRACT_CONCURRENCY=3,
EMBEDDING_BATCH_SIZE=10, MAX_GLEANING=0
```

**Existing .env overrides** (already applied):
```
MAX_ASYNC=7, ENTITY_EXTRACT_CONCURRENCY=4, MAX_GLEANING=0
```

All tunables are already read from environment variables — no code changes are needed. This change is purely configuration-driven.

## Goals / Non-Goals

**Goals:**
- Reduce per-document processing time by 40-60% through configuration defaults alone
- Document the tuning knobs so users can adjust for their workload
- Add entity quality filtering (minimum graph degree) to reduce noise

**Non-Goals:**
- Code-level pipeline refactoring (parallelizing the merge algorithm, replacing LightRAG internals)
- Changing the LLM provider or model
- Implementing batch embedding across LightRAG's internal pipeline
- Any changes requiring `process_worker.py` or `raganything/config.py` code modifications

## Decisions

### Decision 1: Raise defaults in `.env` comments vs change `process_worker.py` hardcoded defaults

**Chosen: Keep code defaults, raise in `.env`**

- **Rationale**: The hardcoded defaults in `process_worker.py` (`_env_int("MAX_ASYNC", 4)`) serve as safe floor values that work with any API provider. Raising them globally could break users with strict rate limits. Instead, we raise the values in `.env` along with explanatory comments so users opt in.
- **Alternative considered**: Changing `_env_int("MAX_ASYNC", 4, max_val=16)` to `_env_int("MAX_ASYNC", 8, max_val=16)`. Rejected because it's a breaking change for users without DashScope's QPS headroom.

### Decision 2: `CHUNK_SIZE` trade-off — fewer large chunks vs more small ones

**Chosen: Raise from 800 → 1400**

- **Rationale**: Doubling chunk size halves the number of LLM extraction calls. For Chinese text (where each character is ~0.5-1 token), 1400 tokens ≈ 2800 characters, which is a reasonable paragraph size. Entity extraction quality does not degrade because the LLM context window is large enough.
- **Risk**: Very long paragraphs (<5% of documents) may exceed 1400 tokens and get split anyway.

### Decision 3: MAX_ASYNC ceiling — 12 vs 14 vs 16

**Chosen: 12**

- **Rationale**: `graph_max_async = MAX_ASYNC * 2 = 24` concurrent merge operations. At this level, the bottleneck shifts from LLM concurrency to keyed-lock contention on shared entity names. 12 provides good throughput without triggering DashScope free-tier QPS limits.
- **Alternative considered**: 14 (graph_max_async=28). Rejected as diminishing returns — the keyed locks serialize most operations anyway.

### Decision 4: ENTITY_EXTRACTION_MIN_DEGREE default

**Chosen: 1 (from 0)**

- **Rationale**: Entities with degree 0 have zero relations — they contribute nothing to graph traversal and only add noise. Setting the default to 1 removes truly isolated nodes while preserving all connected entities.
- **Alternative considered**: 2. Rejected as too aggressive for small KBs where even degree-1 entities are valuable for discovery.

## Risks / Trade-offs

- **[API Rate Limiting]**: Raising `MAX_ASYNC` from 7→12 increases peak QPS by ~70%. DashScope free tier may throttle → **Mitigation**: Keep code defaults low; users can revert via `.env` if throttled.
- **[Memory]**: `MAX_CONCURRENT_FILES=2→3` increases worker subprocess count and memory usage → **Mitigation**: Only recommended for machines with ≥16GB RAM; documented as optional.
- **[Entity Quality]**: `MIN_DEGREE=1` removes isolated entities that might still be useful for keyword search → **Mitigation**: Entity names still appear in full-text chunks; RRF retrieval uses BM25+Vector channels that are unaffected.

## Open Questions

- What is the exact QPS limit for the user's DashScope tier? (Would enable more aggressive tuning)
- Should `CHUNK_SIZE` be auto-scaled based on document length? (Out of scope for this change)
