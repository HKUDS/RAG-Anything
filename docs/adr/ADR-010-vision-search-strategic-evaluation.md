# ADR-010: Vision Search vs. Referenced Images — Strategic Evaluation

## Status
Proposed (note: ADR-008 and ADR-009, which this ADR references, are also in Proposed status; their acceptance status affects this ADR's authority chain)

## Context

RAG-Anything currently has two distinct image retrieval capabilities:

**Feature A: Referenced Images (text-to-image discovery)** -- ~328 LOC in `raganything/routers/shared.py` (lines 172-451) and `raganything/routers/agent.py` (lines 618-649, 798-821). A three-pass cascade that runs automatically after every text query:

1. Regex extraction of image paths from retrieval context (`extract_image_paths`, ~17 LOC)
2. Knowledge graph traversal for image-type entities via `_discover_images_via_graph` (~146 LOC)
3. Character-bigram full-scan of the entire text chunk store via `_bigram_image_scan` (~70 LOC)

Each pass only fires if the prior one found no images. Results include contextual text backfill (up to 4800 characters). Dependencies: reads `kv_store_text_chunks.json` (local file) and calls `graph_retriever.search_with_paths()` (in-process). Zero API calls. Zero marginal cost per query.

**Known failure modes and scaling limits:**
- **Pass 1 (regex extraction)**: Effectively no failure mode -- operates on in-memory string. Returns empty list on no match.
- **Pass 2 (graph traversal)**: `graph_retriever` may be None (graph search not configured); `search_with_paths` may timeout (8s timeout, 3 retries); no image-type entities found in graph results. All return `([], "")` gracefully.
- **Pass 3 (bigram scan)**: `kv_store_text_chunks.json` missing or corrupted. Unhandled JSON decode error (would propagate as exception caught at caller). **Scaling concern**: the bigram scan loads ALL text chunks into memory and iterates every chunk. On the current largest known KB (~50K chunks, ~25MB JSON), this completes in acceptable time. At 10x scale (500K chunks), the O(N) scan would become a latency bottleneck. The proposed improvement (embedding-based re-ranker using existing `chunks_vdb` vectors) would replace this O(N) scan with O(log N) vector search at zero additional API cost.
- **Overall**: All three passes are wrapped in try/except at the call site (`agent.py:646`, `agent.py:818`), so any unexpected failure degrades to empty image results rather than crashing the query.

**Feature B: Vision Search (image-to-image similarity)** -- ~920 LOC across `raganything/embedding/image_vector_repo.py` (303 lines), `raganything/embedding/doubao_vision.py` (513 lines), `raganything/modalprocessors/image.py` (lines 345-397), `raganything/routers/agent.py` (lines 396-478), and `raganything/raganything.py` (lines 537-580). Two-phase architecture:

- **Ingest**: During document processing, every image goes through VLM description + doubao-embedding-vision API call (2048-dim vector) + storage in NanoVectorDB (`vdb_image_vision.json`) with content-hash dedup (SHA-256). Runs in worker subprocess.
- **Query**: User-uploaded image triggers parallel VLM description + vision embedding API call, then cosine similarity search in NanoVectorDB (top_k=5, threshold=0.4). Server must explicitly `repo.reload()` before each query to pick up worker writes.

Infrastructure: paid Doubao API calls per image at both ingest and query time (Doubao is ByteDance's vision embedding service, accessed via `doubao-embedding-vision-251215` model through a Volcengine Ark API endpoint), NanoVectorDB file with atomic write rotation (tmp + replace + backup), multi-process coordination (worker writes, server reloads), and 10+ distinct failure modes with graceful degradation at each point.

### The Core Question

These features solve **different** problems -- Referenced Images answers "what images are related to my text query?" while Vision Search answers "what images look visually similar to this uploaded image?" The question is whether the marginal value of Vision Search justifies its infrastructure cost, or whether Referenced Images already provides sufficient image discovery at zero marginal cost.

### How We Got Here

ADR-008 (Proposed) established the `image_vision_vdb` storage pattern, and ADR-009 (Proposed) defined the query architecture. Both were designed with careful consideration of the vision embedding space. However, the actual implementation diverged materially from both ADRs:

- ADR-008 specified using the existing `NanoVectorDBStorage` wrapper class; the implementation uses a standalone `ImageVectorRepository` with its own atomic persistence, reload mechanism, and crash recovery logic.
- ADR-009 specified a dedicated REST endpoint with a three-tier degradation model (501/503/200); the implementation integrates vision search into the agent query streaming endpoint (`agent_query_stream`) and adds a secondary REST endpoint.
- ADR-009's recommendation of "explicit opt-in context enrichment" (vision results as pre-retrieval text augmentation) was not implemented; instead vision results are returned as inline SSE events alongside text results.

Note: both ADR-008 and ADR-009 are themselves in Proposed status, not Accepted. The divergences are observations about implementation-vs-design-intent, not violations of ratified decisions. Whether these divergences represent intentional improvements (in which case the ADRs should be updated to reflect reality) or unintentional drift (in which case the code should be refactored to match the ADRs) is unresolved -- and resolving that question is itself non-trivial work that should not be undertaken without validated user demand.

## Options Considered

### Option A: Fix and Invest in Vision Search

Repair the known reliability issues (VDB staleness, multi-process coordination, API fallback), align implementation with ADR-008/009, add monitoring and automated tests, and promote Vision Search to a GA feature.

**Pros:**
- Preserves the unique image-to-image similarity capability (no alternative exists in the system)
- Completes the architectural vision laid out in ADR-008/009
- The content-hash dedup (SHA-256) prevents storing duplicate image vectors -- an image reuse detection capability that no other system component provides
- The VLM description generated during the vision pipeline adds valuable image metadata that can improve text search quality even without vision similarity queries (the VLM captions enrich the knowledge graph entity descriptions)
- NanoVectorDB is already an in-project dependency (used by `chunks_vdb`, `entities_vdb`, `relationships_vdb`); vision search adds no new database dependency
- Enables future modalities (video keyframes, audio spectrograms) that could reuse the same embedding-storage-query pattern

**Cons:**
- High engineering effort (estimated 3+ person-months to harden, test, monitor, and document)
- Ongoing operational cost (doubao-embedding-vision API calls per image at ingest AND query time, scaling linearly with document/image count)
- Serves a niche use case (image-to-image similarity queries) with no validated user demand
- Multi-process VDB consistency (worker subprocess writes + server reloads) has no simple solution -- the current reload-on-every-query pattern is a workaround, not a fix
- The RICE (Reach x Impact x Confidence / Effort) gap vs. Referenced Images suggests extremely low ROI. See RICE decomposition under Decision rationale.
- Each of the 10+ failure modes must be monitored, alerted, and documented -- ongoing maintenance burden
- No test coverage exists for any vision search code path

**What we give up:** 3+ person-months of engineering capacity that could improve features affecting 100% of users (text retrieval quality, VLM image QA, UI polish). Ongoing API cost budget. System simplicity -- every additional VDB and external API dependency increases the mental model for new contributors.

### Option B: Deprecate Vision Search, Invest in Referenced Images

Remove Vision Search code (feature flag it off, then remove after one release cycle), and redirect all image retrieval investment into improving Referenced Images.

**Pros:**
- Eliminates all Vision Search infrastructure costs (API calls, VDB management, multi-process coordination, 920 LOC of maintenance surface)
- Frees 3+ person-months for higher-ROI investments
- Simplifies the system architecture -- one less VDB, one less external API dependency, one less multi-process coordination problem
- Referenced Images is zero-cost, production-stable, and available to 100% of query users automatically
- The knowledge graph traversal in Referenced Images (`_discover_images_via_graph`) is architecturally distinctive -- it leverages the entity graph that makes RAG-Anything unique, rather than replicating a commodity embedding similarity pipeline
- Aligns with the upstream project's (HKUDS LightRAG) philosophy of graph-augmented retrieval

**Cons:**
- Loses the unique image-to-image similarity capability entirely
- If user demand for visual similarity search materializes, re-adding it later requires rebuilding the embedding pipeline from scratch (though the ADRs and git history preserve the design)
- Users who have already built workflows around Vision Search (if any exist) would experience feature removal
- The `vdb_image_vision.json` files in existing KBs become dead weight
- ADR-008 and ADR-009 become historical documents rather than living design references

**What we give up:** The ability to answer "find images that look like this one." The competitive differentiation (if any) of having an image-to-image search capability. The architectural foundation for future vision-based modality stores.

### Option C: Hybrid -- Keep Vision Search Code, Defer Fix, Improve Referenced Images Now

Keep Vision Search code in the tree but explicitly mark it as experimental/unsupported. Invest immediate effort in improving Referenced Images. Set concrete gates that must be met before Vision Search can be promoted to GA.

**Pros:**
- No code removal -- Vision Search remains available for experimentation and demos
- No disruption to any existing Vision Search users (if any)
- Immediate engineering investment goes to the higher-ROI feature (Referenced Images)
- Preserves the code as a reference implementation for the vision embedding pattern
- Creates a clear, measurable bar for Vision Search GA readiness (user demand data, reliability targets, cost analysis)
- Reversible: if user demand materializes, the code is already there; if not, removal is a cleanup task, not a rebuild

**Cons:**
- Dead code risk: Vision Search may linger indefinitely in an "experimental" state, accumulating bit rot
- The Multi-process VDB coordination problem (VDB staleness) could silently corrupt results for anyone who does try Vision Search
- New contributors may spend time understanding Vision Search code that ultimately gets removed
- The feature flag is not a substitute for a decision -- "defer" can become "never decide"
- Two separate image retrieval code paths to maintain (even if one is frozen)

**What we give up:** Decisiveness. The team carries the cognitive overhead of two image retrieval systems. The "experimental" label may not prevent users from depending on it.

## Decision

**We choose Option C: Hybrid -- Keep Vision Search code, defer fix, invest in Referenced Images now.**

### Rationale

The decision is driven by four architectural principles and the evidence gathered from code analysis and product evaluation:

**1. Reversibility matters more than optimality.** Removing Vision Search (Option B) is a one-way door -- the code is deleted, the embedding pipeline must be rebuilt from scratch if demand materializes. Keeping the code behind a feature flag (Option C) is a two-way door -- we can always remove it later, but we cannot easily reconstruct it later. In the current product stage (pre-scale, no validated user demand data for image-to-image search), preserving optionality is worth the carrying cost.

**2. Cost-to-value ratio is unacceptable for Option A.** The Codebase Onboarding Engineer's exhaustive trace reveals that Vision Search spans ~920 LOC with 10+ distinct failure modes, requires paid API calls at both ingest and query time, and has a multi-process data consistency problem (worker writes require explicit server `reload()`) that has no simple solution.

**RICE decomposition** (scored by Product Manager, 70% confidence overall):

| Component | Vision Search | Referenced Images | Methodology |
|-----------|---------------|-------------------|-------------|
| **Reach** (users/quarter affected) | 50 (niche image-search users) | 1,000 (all query users, automatic trigger) | Estimated from query flow analysis |
| **Impact** (0.25/0.5/1/2/3) | 0.5 (unique but narrow capability) | 1 (meaningful enhancement, not transformative) | PM judgment based on user journey analysis |
| **Confidence** (%) | 50% (fragile infrastructure, unclear adoption) | 85% (simple, well-understood mechanism) | Evidence maturity assessment |
| **Effort** (person-months) | 3+ (hardening, monitoring, VDB consistency, API fallback) | 0.5 (already built and stable) | Engineering estimate |
| **RICE Score** | (50 x 0.5 x 0.50) / 3 = **4.2** | (1000 x 1 x 0.85) / 0.5 = **1,700** | |

The 400x gap is driven primarily by Reach (20x) and Confidence (1.7x). Even if we adjust assumptions -- triple Vision Search's Reach to 150, double its Impact to 1.0, halve its Effort to 1.5 -- the RICE score becomes (150 x 1 x 0.50) / 1.5 = 50, still a 34x gap. The conclusion is robust to significant assumption changes.

Investing 3+ person-months to harden a feature with unvalidated demand and high operational cost fails the basic product test of "build the right thing before building the thing right."

**3. Referenced Images leverages the system's architectural moat.** Graph-augmented RAG is not unique to RAG-Anything -- Microsoft's GraphRAG, Neo4j-based RAG systems, and several open-source projects combine knowledge graphs with retrieval. What IS distinctive is the specific three-pass cascade architecture that degrades gracefully from regex extraction to graph traversal to full-scan -- with zero API cost and automatic triggering on every text query. Individual components (regex extraction, graph traversal) are replicable; the integrated zero-cost cascade with automatic backfill is harder to replicate. Vision embedding similarity, by contrast, is a commodity feature -- CLIP-based image search is available in dozens of open-source tools. Investing in graph-aware image discovery strengthens the moat; investing in vision embedding similarity makes us more like everyone else.

**4. The implementation has already diverged from the ADRs, creating architectural debt.** ADR-008 specified using the existing `NanoVectorDBStorage` wrapper. The implementation uses a standalone `ImageVectorRepository` with its own atomic persistence. ADR-009 specified a dedicated REST endpoint with a three-tier degradation model. The implementation integrates into the streaming agent query endpoint. Before Vision Search can be promoted to GA, these divergences must be resolved -- either by updating the ADRs to reflect the actual implementation (if the divergences were intentional improvements), or by refactoring the code to match the ADRs (if the divergences were unintentional). This is non-trivial work that should not be undertaken without validated user demand.

### Concrete Gates for Vision Search GA Promotion

Vision Search will not be invested in further until **at least two** of the following gates are met:

| Gate | Threshold | Measurement |
|------|-----------|-------------|
| User demand signal | >10% of users attempt image upload in query flow | Analytics on `req.image` field presence in `agent_query_stream` |
| Qualitative validation | At least 5/10 moderated user tests show image-to-image search as a top-5 pain point | Structured user interviews |
| Revenue signal | A signed enterprise contract contingent on vision search capability | Sales pipeline data |
| Competitive necessity | A major competitor ships vision similarity search that drives churn | Competitive intelligence |

**Sunset clause**: If none of the above gates are met within **12 months** of this ADR's acceptance, Vision Search code shall be removed in the following release cycle. This prevents indefinite limbo -- the decision has a defined expiration date. If gates ARE met within 12 months, this ADR should be revisited and either superseded by an "invest in Vision Search" ADR or confirmed as still applicable with updated rationale.

### Immediate Investment: Improve Referenced Images

The following improvements to Referenced Images are higher-ROI than any Vision Search work:

1. **Replace bigram scan with semantic matching** (~1 person-week): The current `_bigram_image_scan` uses character-level bigram overlap scoring, which is a creative but noisy heuristic. Replace with a lightweight embedding-based re-ranker on existing text chunk embeddings (using the already-computed text vectors in `chunks_vdb`, still zero additional API cost). This would dramatically improve the relevance of discovered images.

2. **Add image thumbnail previews in results** (~0.5 person-weeks): The current implementation returns image paths that must be fetched separately. Pre-computing or caching thumbnail URLs would improve the user experience.

3. **Surface graph traversal paths in results** (~0.5 person-weeks): When `_discover_images_via_graph` finds images, show the entity relationship path that connected the query to the image (e.g., "Found via: `query -> Entity A -> belongs_to -> Image X`"). This makes the graph-aware discovery transparent and builds user trust.

4. **Add test coverage** (~0.5 person-weeks): Neither feature has any test coverage. At minimum, add unit tests for `extract_image_paths`, `_build_backfill_context`, and `_bigram_image_scan` to prevent regressions during improvement.

**Total estimated investment**: ~2.5 person-weeks, vs. 3+ person-months for Vision Search hardening. Roughly a 5:1 effort ratio.

### Architectural Note: The Knowledge Graph is the Moat

It is worth stating explicitly: the strategic differentiator in RAG-Anything's image retrieval is not "can we find visually similar images" (any CLIP-based system can), but "can we find images that are semantically connected to the user's query through the knowledge graph." The `_discover_images_via_graph` function does exactly this -- it traverses entity relationships to find images associated with entities that match the query. This is architecturally distinctive and harder to replicate. Future image retrieval investment should double down on this graph-aware approach, not on commodity vision embedding similarity.

## Consequences

### What becomes easier

- **Engineering focus**: The team stops splitting attention between two image retrieval systems and concentrates on making the zero-cost, high-reach system excellent.
- **Operational simplicity**: No monitoring, alerting, or debugging for Vision Search API failures, VDB corruption, or multi-process staleness.
- **Cost predictability**: No variable API cost from vision embedding calls. The image retrieval path has zero marginal cost per query.
- **Onboarding speed**: New contributors learn one image retrieval system (the three-pass cascade) instead of two with different architectures, dependencies, and failure modes.
- **Future optionality**: Vision Search code is preserved in tree. If demand materializes, the code is a starting point, not a blank page.

### What becomes harder

- **Image-to-image search**: Users who want "find images that look like this uploaded image" have no supported path. The code exists but is not maintained or reliability-guaranteed.
- **Visual deduplication**: The content-hash dedup in Vision Search (detecting identical images across documents) is lost if Vision Search is not maintained. This is a separate concern from similarity search and could be extracted as a standalone feature.
- **Future modality vector stores**: The Vision Search code was intended as a template for video keyframes, audio spectrograms, etc. If it bit-rots, that template becomes less reliable.
- **Codebase clarity**: Two image retrieval code paths coexist in the tree, one supported and one experimental. New contributors must be explicitly told which is which.
- **Decision accountability**: "Defer" is not "decide." The team must actively revisit this ADR when the gates are met, or the sunset clause triggers automatic removal at 12 months. Without active governance, Option C decays into indefinite limbo -- the sunset clause is the backstop.

## References

- ADR-008: Add Image Vision Vector Database (`image_vision_vdb`) -- storage design
- ADR-009: Vision Search API Integration and Query Architecture
- `raganything/routers/shared.py` lines 172-451 -- Feature A implementation (extract_image_paths, _discover_images_via_graph, _bigram_image_scan)
- `raganything/routers/agent.py` lines 618-649, 798-821 -- Feature A orchestration
- `raganything/routers/agent.py` lines 396-478 -- Feature B query path (_run_vlm_desc, _run_vision_search, parallel dispatch)
- `raganything/embedding/image_vector_repo.py` -- Feature B VDB management (ImageVectorRepository)
- `raganything/embedding/doubao_vision.py` -- Feature B API client (DoubaoEmbeddingAdapter)
- `raganything/modalprocessors/image.py` lines 345-397 -- Feature B ingest path (_compute_and_store_vision)
- `raganything/raganything.py` lines 537-580 -- Feature B initialization (_init_vision_repo)
