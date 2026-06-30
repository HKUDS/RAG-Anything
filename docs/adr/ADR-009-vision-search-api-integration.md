# ADR-009: Vision Search API Integration and Query Architecture

## Status
Proposed

## Context

ADR-008 establishes a dedicated `image_vision_vdb` NanoVectorDB for storing vision embeddings of images. With the storage layer defined, the remaining architectural question is: **how should vision embeddings be exposed through the query API?**

The system currently has three query surfaces:
1. `aquery(query, mode)` -- pure text RAG (supports `mix`, `hybrid`, `naive`, `local`, `global`, `rrf`, `graph`)
2. `aquery_with_multimodal(query, multimodal_content, mode)` -- query enriched with uploaded images/tables/equations (VLM describes them, then text-enhanced query runs)
3. `aquery_vlm_enhanced(query, mode)` -- retrieves context, replaces image paths with base64 images, VLM answers

None of these surfaces support direct image-to-image similarity search. The vision embedding model (`doubao-embedding-vision`) produces vectors in a different semantic space than text embeddings -- visual similarity, not semantic meaning. This creates a fundamental type mismatch when considering how to integrate vision search results with the existing text retrieval pipeline.

Three independent expert reviews (AI Engineer, Backend Architect, Database Optimizer) all identified the same core architectural constraint: **vision similarity scores and text relevance scores operate in incommensurable metric spaces**. Fusing them into the same ranking formula (RRF or otherwise) produces a ranked list where the meaning of position N is undefined.

## Decision

**Adopt a two-mode architecture: (1) a dedicated vision search endpoint for pure image-to-image similarity, and (2) an explicit opt-in context-enrichment path within the existing multimodal query endpoint.**

Vision search is NOT added as a 4th channel in RRF fusion. Instead, it operates as either a standalone retrieval mode or a pre-retrieval context enrichment step.

### Mode 1: Dedicated Vision Search Endpoint

```
POST /api/vision/search
```

A new endpoint in `raganything/routers/knowledge.py`, alongside the existing `/api/upload` endpoint. Both are KB-scoped, file-oriented operations.

This endpoint accepts a multipart image file upload and returns the top-K visually similar images from the target KB, ranked by cosine similarity of vision embeddings.

**Request (multipart/form-data)**:
```
file: <image_file>          (required, max 20MB, JPEG/PNG/WebP)
top_k: 5                    (optional, default 5, range 1-20)
similarity_threshold: 0.5   (optional, default 0.5, range 0.0-1.0)
include_text_context: true  (optional, default true)
kb: "default"              (optional, defaults to user's active KB)
```

**Response (JSON)**:
```json
{
  "status": "ok",
  "query_image_info": {"filename": "query.jpg", "size_bytes": 123456},
  "results": [
    {
      "image_path": "output/images/part_abc.png",
      "image_url": "/api/files/image/part_abc.png",
      "similarity_score": 0.94,
      "vlm_description": "CNC-machined aluminum bracket with 4 holes",
      "source_document_name": "零件手册_第三章.pdf",
      "source_document_id": "doc_abc123",
      "linked_entities": ["铝合金支架 (Part)", "CNC加工 (Process)"],
      "linked_text_chunks": ["铝合金支架采用CNC四轴加工中心进行精密加工..."]
    }
  ],
  "total_indexed_images": 1042,
  "elapsed_ms": 245.3,
  "degraded": false,
  "degraded_reason": null
}
```

### Mode 2: Explicit Opt-In Context Enrichment

Within `aquery_with_multimodal`, add a `vision_search: bool = False` parameter. When `True` and an image is present in `multimodal_content`:

1. Extract the first image from `multimodal_content`
2. Compute its vision embedding via `vision_embedding_func`
3. Query `image_vision_vdb` for top-5 visually similar images
4. Load the VLM descriptions and linked text chunks of those similar images
5. Append this retrieved text as supplementary context to the text query
6. Run the existing text RRF pipeline against the enhanced query

The vision search acts as a **pre-retrieval context enrichment step**, not as a competing retrieval channel. The retrieved text from similar images participates in RRF fusion naturally because it is now text, not vision vectors.

```python
result = await rag.aquery_with_multimodal(
    query="What process does this part belong to?",
    multimodal_content=[{"type": "image", "img_path": "query_part.jpg"}],
    vision_search=True,  # explicit opt-in
    mode="rrf",
)
```

### What We Explicitly Reject

**Rejected: Vision search as a 4th RRF channel.** RRF fusion assumes all channels return the same candidate type (document chunks identified by `chunk_id`) and that ranking signals are commensurable. Adding vision search as `channel_4` would introduce image results (identified by `image_path`) with scores from a different distance function (cosine in CLIP space vs BM25 IDF-weighted term frequency vs dot product in text embedding space). The fusion formula `1/(k + rank_i)` produces a single ranked list, but comparing "chunk ranked #1 in BM25" against "image ranked #1 in vision cosine" is meaningless -- there is no shared ground truth.

**Rejected: Auto-triggering vision search on every multimodal query.** Uploading a screenshot of a text paragraph produces near-zero CLIP similarity to document images. Auto-trigger produces confusing empty results where text search would have worked. Additionally, each auto-triggered call exposes the embedding API to unintended use and increases cost.

## Architecture

### Endpoint Placement

```
raganything/routers/knowledge.py   ← POST /api/vision/search (NEW)
raganything/routers/agent.py       ← existing query endpoints, no change
```

The rationale for placing vision search in the knowledge router rather than the agent router:

| Factor | Knowledge Router | Agent Router |
|--------|-----------------|-------------|
| Scope | KB-scoped resource operations | Agent-scoped conversation interactions |
| Existing endpoints | `/api/upload`, KB CRUD | `/agents/{id}/query/stream` |
| Data model | Works with files, KB metadata | Works with conversations, messages |
| Authorization | `verify_kb_access(kb, user)` | Agent-scoped auth |
| Rate limit budget | Separate from chat | Would share chat's generous 30/min pool |

### Three-Tier Degradation Model

| Tier | Condition | HTTP Status | User Experience |
|------|-----------|-------------|----------------|
| Tier 1: Feature disabled | `VISION_SEARCH_ENABLED` env var is `false` or unset | **501 Not Implemented** | Frontend hides "Visual Search" button entirely. API returns `{"error_code": "FEATURE_DISABLED"}` |
| Tier 2: Service unavailable | API key set but embedding service fails (circuit breaker open after 5 consecutive failures) | **503 Service Unavailable** | Frontend shows "Visual search temporarily unavailable" with retry countdown. `Retry-After` header set. |
| Tier 3: Empty index | Service healthy but KB has zero indexed images | **200 OK** with `status: "empty"` | Frontend shows "This knowledge base has no images for visual search. Upload documents to enable." |

Key principle: NEVER silently fall back to text-only search. Silent fallback produces "no results" that is indistinguishable from "your image genuinely has no matches," destroying user trust.

### Feature Flag Gating

```python
# Environment variables (in .env or system)
VISION_SEARCH_ENABLED=false              # Master kill switch (default: OFF)
VISION_EMBEDDING_MODEL=doubao-embedding-vision  # Model name
VISION_EMBEDDING_API_KEY=<key>           # API key (can reuse LLM_BINDING_API_KEY)
VISION_EMBEDDING_BASE_URL=<url>          # Base URL (can reuse LLM_BINDING_HOST)
VISION_EMBEDDING_DIM=                    # Optional: force dimension (auto-detect if unset)
VISION_EMBED_MAX_CONCURRENT=3            # Max concurrent vision embedding API calls
```

When `VISION_SEARCH_ENABLED` is `false`, the server starts normally but `/api/vision/search` returns 501. The `vision_embedding_func` is not created, and `image_vision_vdb` is not initialized.

### Capability Endpoint

To enable the frontend to conditionally show UI elements:

```
GET /api/kb/{name}/capabilities

Response:
{
  "kb_name": "default",
  "vision_search": true,
  "vision_embedding_model": "doubao-embedding-vision",
  "vision_indexed_images": 1042
}
```

Frontend uses this response to show/hide the "Visual Search" button and display index status.

### Security Controls

The vision search endpoint requires the following security controls, identified by the Security Architect review:

1. **Magic byte verification**: Validate uploaded image format by file header bytes, not extension. Add to `raganything/utils/_image.py:validate_image_file()`.
2. **PIL decompression bomb guard**: Set `PIL.Image.MAX_IMAGE_PIXELS = 50_000_000` (50 megapixels max) in `modalprocessors/image.py`.
3. **EXIF/metadata stripping**: Strip all metadata after PIL validation; only raw pixel data reaches the embedding API.
4. **Dual-key rate limiting**: `5/minute` per IP + `20/hour` per authenticated user. Vision embedding API calls are expensive and must not be abusable.
5. **RAG context sanitization**: VLM-generated image descriptions entering the knowledge graph must pass `PROMPT_INJECTION_REGEX` check (same as user queries).
6. **Path traversal prevention**: `kb_dir(name)` return value must be resolved and verified to be within the expected storage root before constructing `vdb_vision.json` path.

### Pre-Existing Bug: `verify_kb_access`

The Security Architect identified that `allowed_kbs` field in `raganything/dependencies.py:215` is never populated. This means KB-scoped access control is effectively non-functional for all endpoints using `verify_kb_access`. This is a pre-existing bug that must be fixed before any new KB-scoped endpoint (including `/api/vision/search`) is deployed.

## Query Pipeline Integration

### When `vision_search=True` in `aquery_with_multimodal`

```
User Request: query="What process?" + image.jpg + vision_search=True
    │
    ├── Step 1: VLM describes query image → "A CNC-machined aluminum bracket"
    │
    ├── Step 2: Vision embedding(image.jpg) → 1024d vision vector
    │       └── Query image_vision_vdb (cosine, top_k=5)
    │           └── Returns: [part_abc.png(0.94), bracket_xyz.png(0.87), ...]
    │
    ├── Step 3: For each similar image, load its stored VLM description
    │       and linked text chunks from text_chunks KV
    │       └── Supplementary context:
    │           "铝合金支架 (Part): CNC四轴加工..." (from part_abc.png)
    │           "支架固定方式 (Process): 采用M6螺栓..." (from bracket_xyz.png)
    │
    ├── Step 4: Build enhanced_query = query + VLM_description + supplementary_context
    │
    └── Step 5: Run existing RRF pipeline (BM25 + vector + graph) against enhanced_query
            └── Returns text chunks + LLM answer
```

The vision search is a **context enrichment pre-step**. It never produces results directly -- it enriches the text query so the text pipeline can find more relevant content.

### No Change to Default Query Path

`aquery(query, mode, ...)` without `multimodal_content` or with `vision_search=False` (the default) follows the identical code path as today. Zero regression risk for existing queries.

## Trade-offs and Alternatives Considered

### Alternative A: Blend vision vectors into entities_vdb with a type discriminator

Add vision vectors to `entities_vdb` entries with `entity_type: "image"` and a separate vector field.

**Rejected because**: Already covered in ADR-008 Alternative D. Additionally: entities_vdb queries return entities matching ANY vector, mixing visual-similarity results with semantic-similarity results in one undifferentiated list. The caller cannot distinguish "this entity was matched because its text description contains similar words" from "this entity was matched because its image looks similar." The two match types require different presentation -- text matches show excerpt text, image matches show thumbnails.

### Alternative B: Vision search as a separate microservice

Deploy vision embedding and search as an independent service with its own API.

**Rejected because**: Adds deployment complexity disproportionate to the feature scope. The vision embedding model is accessed through the same API infrastructure (OpenAI-compatible endpoint, same API key management). A separate service would need its own storage, its own KB-scoping logic, and its own authorization layer -- duplicating infrastructure that already exists in the RAG-Anything server.

### Alternative C: Return vision search results as inline markdown in text answer

Rather than a structured JSON response, embed vision results as markdown in the LLM's text answer.

**Rejected because**: This conflates retrieval (what was found) with generation (what the LLM says about it). The frontend cannot render image thumbnails from markdown text without fragile parsing. Structured JSON responses enable the frontend to render vision results in a dedicated visual-matches component, separate from the text answer.

### Alternative D: RRF fusion with normalized scores (attempted but abandoned)

Attempt to normalize vision cosine scores and text BM25/vector scores into a common [0,1] range, then fuse via RRF.

**Investigated and rejected because**: Score normalization cannot fix the fundamental type mismatch. Two images with cosine similarity 0.94 and 0.87 are both "very similar" in vision space. Two text chunks with BM25 scores 0.94 and 0.87 are "top match" and "also relevant" in text space. But when fused, the rankings imply comparability that does not exist. The RRF formula would assign position #1 to an image and position #2 to a completely unrelated text chunk that happens to have a high text score from a different query component. The resulting ranked list is not wrong in a measurable way -- it is wrong in a fundamental, semantic way. This is not a normalization problem; it is a category error.

## Risks and Mitigations

### Risk 1: Vision embedding API returns different dimension than text embeddings
**Severity**: Medium. If the vision model outputs 512d vectors and NanoVectorDB is initialized with 1024d (or vice versa), upserts will fail.
**Mitigation**: Auto-detect dimension from first API call (1x1 pixel probe). Store detected dimension in `vdb_vision_meta.json`. On subsequent initializations, validate that the API still returns the same dimension. On mismatch, refuse to start with clear error message.

### Risk 2: User uploads non-image file to `/api/vision/search`
**Severity**: Low.
**Mitigation**: Server-side validation: (a) content-type check on upload, (b) magic byte verification (JPEG=FFD8, PNG=89504E47, WebP=52494646), (c) PIL can actually open and parse the file. Return 422 with clear error on any failure.

### Risk 3: Embedding API cost amplification
**Severity**: Medium. Each vision search query calls the embedding API (for the query image) plus potentially loads pre-computed embeddings from disk. If rate limiting fails, an attacker could trigger thousands of embedding API calls.
**Mitigation**: Dual-key rate limiting (IP + user). Circuit breaker on embedding API (5 consecutive failures opens the circuit for 30s). Maximum 20MB image size limit. Vision search is explicitly opt-in for multimodal queries.

### Risk 4: Vision embedding model changes and existing vectors become invalid
**Severity**: Low. Covered in ADR-008 Risk 2.
**Mitigation**: `vdb_vision_meta.json` stores model identifier. On startup, if configured model differs from stored model, refuse to start with migration instructions.

## Consequences

### What becomes easier
- **Image-to-image search**: Users can upload a photo and find visually similar images across all documents in a KB
- **Visual deduplication**: Identical images across documents are detected by content hash, reducing storage and API costs
- **Context-enriched multimodal queries**: When a user uploads an image and asks a question, the system finds text about visually similar images, improving retrieval recall for visual topics
- **Staged rollout**: Feature flag (`VISION_SEARCH_ENABLED`) enables gradual deployment. Default off means zero risk to existing installations
- **Capability discovery**: Frontend queries `/api/kb/{name}/capabilities` to conditionally show visual search UI, no hardcoded feature detection

### What becomes harder
- **Error diagnosis**: When vision search returns empty results, users may not understand whether the image is genuinely unique or the feature is misconfigured. The `degraded` field and clear error codes mitigate this but cannot fully eliminate user confusion
- **Load testing**: Vision embedding API latency (200-500ms per image) adds variability to query benchmarks. Load tests must be parameterized by whether vision search is enabled
- **KB migration**: Moving a KB between servers now requires the vision embedding model to be identically configured on both sides, or the `vdb_vision_meta.json` match will prevent startup. This is consistent with other storage migration requirements but adds one more constraint

## Integration Points Summary

| File | Change | Description |
|------|--------|-------------|
| `raganything/routers/knowledge.py` | **NEW endpoint** | `POST /api/vision/search` with multipart file upload |
| `raganything/query/pipeline.py` | **MODIFY** | Add `vision_search` parameter to `aquery_with_multimodal`; add `_enrich_query_with_vision_context()` method |
| `raganything/config.py` | **MODIFY** | Add `enable_vision_search`, `vision_embedding_model`, `vision_embedding_dim` fields to `RAGAnythingConfig` |
| `raganything/raganything.py` | **MODIFY** | Add `vision_embed_func` field to `RAGAnything`; conditional `image_vision_vdb` initialization |
| `raganything/services/kb_service.py` | **MODIFY** | Vision embedding function factory; add to `finalize_storages()` call chain |
| `raganything/utils/_image.py` | **MODIFY** | Add magic byte verification and PIL bomb guard to `validate_image_file()` |
| `raganything/dependencies.py` | **MODIFY** | Fix pre-existing `allowed_kbs` bug (line 215); add KB capability check helper |
| `raganything/processor/embed_processor.py` | **NEW method** | `_embed_and_store_image_vision()` for ingestion-time embedding |
| `raganything/modalprocessors/image.py` | **MODIFY** | Call vision embedding in parallel with VLM description generation |

## References
- ADR-008: Add Image Vision Vector Database (`image_vision_vdb`) -- storage design
- AI Engineer review: Vision embedding function factory, dimension auto-detection, caching strategy
- Backend Architect review: API contract design, RRF fusion analysis, degradation model
- Security Architect review: 20 deployment gates including magic bytes, PIL bomb guard, dual-key rate limiting
- API Tester review: Pydantic model specifications, error response schema
