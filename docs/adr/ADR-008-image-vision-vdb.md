# ADR-008: Add Image Vision Vector Database (`image_vision_vdb`)

## Status
Proposed

## Context

RAG-Anything is a multimodal RAG system that processes documents (PDF, Office, images, video), extracts embedded images, generates text descriptions via VLM (qwen-vl-plus, gpt-4o), and stores those text descriptions as vector embeddings for retrieval. However, **image visual features are never directly embedded**. All image search relies on text descriptions of images, not on the images themselves.

This creates three problems:

1. **Visual similarity blindness.** The system cannot answer "find images that look like this one" because no visual vectors exist. Two visually identical images with different VLM captions (due to model non-determinism or different prompt context) will have different text embeddings and may not co-retrieve.

2. **Cross-modal query gap.** A user who uploads an image and asks "find similar images across my knowledge base" receives results based on VLM-generated text descriptions, not visual features. The VLM may describe the image differently than how related images were described during ingestion, breaking the retrieval chain.

3. **Future modality foundation.** Audio spectrograms, video keyframes, and other visual modalities will face the same gap. Establishing the vision vector pattern now creates a template for future modality-specific vector stores.

The existing storage architecture already demonstrates the pattern of **one VDB per semantic space**: `chunks_vdb` for text chunk embeddings, `entities_vdb` for entity embeddings, `relationships_vdb` for relation embeddings. Adding `image_vision_vdb` follows this established convention.

## Decision

Add a **fourth NanoVectorDB instance**, `image_vision_vdb`, to store vision-model embeddings of extracted images. This VDB will:

- Use the same `NanoVectorDBStorage` wrapper class as the existing three VDBs
- Follow the **identical initialization, lifecycle, workspace isolation, cross-process safety, and persistence patterns** established by `chunks_vdb`, `entities_vdb`, and `relationships_vdb`
- Store **one vector per unique image** (deduplicated by content hash), containing both the vision embedding and metadata linking back to source documents, chunks, and KBs
- Be **optional** — KBs processed without a vision embedding function continue to function with the existing three VDBs, no migration required
- Support a **configurable vision embedding model** with its own dimension (independent of the text embedding dimension)

## Architecture

### Storage Layout

A fourth file joins the existing per-KB directory layout:

```
./rag_storage/                          # KB "default"
  vdb_chunks.json                        # text chunk embeddings (1024d)
  vdb_entities.json                      # entity embeddings (1024d)
  vdb_relationships.json                 # relation embeddings (1024d)
  vdb_image_vision.json                  # NEW: image vision embeddings (configurable dim)
  kv_store_text_chunks.json              # (unchanged)
  kv_store_full_entities.json            # (unchanged)
  ... (all other KV + graph files)
```

### Data Model

Each entry in `image_vision_vdb`:

| Field | Type | Source | Purpose |
|-------|------|--------|---------|
| `__id__` | string (auto) | NanoVectorDB | Unique vector ID, auto-generated |
| `__vector__` | numpy float16 | Vision embedding model | The raw vision vector, not compressed (unlike text vectors) |
| `content_hash` | string | SHA-256 of image bytes | Dedup key — identical images share one vector |
| `img_path` | string (absolute) | Parser output | Path to image file on disk |
| `source_doc_id` | string | Document processor | `doc-<md5hash>` of parent document |
| `chunk_id` | string | Chunk processor | `chunk-<md5hash>` linking to `text_chunks` KV entry |
| `entity_name` | string | ImageModalProcessor | VLM-extracted entity name (links to `entities_vdb`) |
| `file_path` | string | Upload handler | Original uploaded filename |
| `kb_name` | string | KB context | Knowledge base name for multi-KB isolation |

The `content_hash` field serves dual purpose: deduplication (skip re-embedding when the same image appears in multiple uploads) and deletion targeting (locate vectors to remove when a document is deleted).

### Data Flow

```
Upload → Parse (MinerU/Docling) → Content List
  │
  ├─ Text items → LightRAG ainsert → chunks_vdb + entities_vdb + relationships_vdb
  │
  └─ Image items → VLM captioning (existing) → text_chunks KV
       │
       └─ NEW: Vision embedding function
            │
            ├── Dedup check: SHA-256(image bytes) lookup in image_vision_vdb
            │   ├─ HIT: Record source_doc_id + chunk_id cross-reference (skip re-embed)
            │   └─ MISS: Encode image → upsert to image_vision_vdb
            │
            └─ Persist via index_done_callback() (same pattern as other VDBs)
```

### Query Integration

Vision vectors are NOT fused into the default RRF retrieval path on every query — that would add latency for queries where visual similarity is irrelevant. Instead, the design offers two integration modes:

1. **Explicit vision query** (`query_mode="vision"` or `query_mode="hybrid-vision"`): Queries `image_vision_vdb` directly using either a user-supplied image or text-to-vision embedding (if the vision model supports text input, e.g., CLIP). Results fuse with text retrieval via an additional RRF round.

2. **Passive enrichment** (future): Retrieved text chunks that have an associated `chunk_id` in `image_vision_vdb` can surface the linked image as supplementary context during VLM-enhanced queries, without changing the retrieval algorithm.

## Trade-offs and Alternatives Considered

### Alternative A: Store vision vectors in `chunks_vdb` alongside text vectors

Extend the existing `chunks_vdb` entries with an additional `vision_vector` field.

**Rejected because:**
- Mixes two embedding spaces (text 1024d + vision 768d) in one VDB, breaking the fixed-dimension assumption baked into NanoVectorDB's constructor (`NanoVectorDB(embedding_dim, ...)` takes a single dimension)
- Forces text and vision vectors to share the same cosine threshold, but optimal thresholds differ (text embeddings typically benefit from `cosine > 0.0` to `0.2`; vision embeddings often need `cosine > 0.7` to filter noise)
- Violates the established architectural pattern of **one VDB per semantic space** — the system already separates chunks, entities, and relationships for exactly this reason
- Makes independent lifecycles impossible (you cannot drop and rebuild vision vectors without touching text vectors)

### Alternative B: External vector database (Milvus/Qdrant/Weaviate)

Use a separate vector database service instead of NanoVectorDB.

**Rejected because:**
- Adds operational complexity (another service to deploy, monitor, and maintain)
- Breaks the self-contained per-KB directory pattern that makes KBs portable (a single `./rag_storage_mykb/` directory contains everything)
- Cross-process safety and workspace isolation would need reimplementation against the external DB's semantics
- The system currently has zero external service dependencies beyond the LLM/VLM/embedding APIs — adding a vector DB service changes the deployment model from "Python process + API keys" to "Python process + API keys + vector DB cluster"
- Overkill for the expected scale (KB with thousands of images, not millions)

### Alternative C: Reuse the existing VLM for on-the-fly image comparison

Instead of pre-computing vision embeddings at ingestion time, use the VLM to compare the query image against all stored images at query time.

**Rejected because:**
- O(N) VLM calls per query, where N is the number of images in the KB — prohibitively expensive and slow (100 images = 100 VLM calls, each ~2-5 seconds)
- VLM comparison is not a vector similarity operation; it returns unstructured text, making ranking and thresholding ad-hoc
- No ability to pre-index or cache comparisons
- Different VLM models produce incomparable outputs, making results model-dependent

### Alternative D: Store vision vectors in `entities_vdb`

Attach vision vectors to image entities already stored in `entities_vdb`.

**Rejected because:**
- `entities_vdb` has dimension 1024 and cosine threshold tied to the text embedding model
- Entities represent named concepts extracted by the LLM, not visual features of images — mixing the two conflates semantic identity with visual appearance
- Image entities are a subset of all entities; creating a separate VDB avoids polluting the entity store with dimension mismatches
- Entity deletion cascades (when a document is deleted) would need to distinguish text-entity vectors from vision-entity vectors within the same store, adding complexity

## Key Design Decisions

### DD-1: One vector per image (not per chunk)

Images are not chunked in the same way text is. A single image in a PDF page is a coherent visual unit. Producing one vision vector per image aligns with:
- **Image atomicity**: An image is a single visual concept
- **Storage efficiency**: One 768d float16 vector = ~1.5KB per image vs. N vectors for N pseudo-chunks
- **Query semantics**: "Find images like this one" is inherently per-image
- **Dedup naturalness**: Content-hash dedup maps 1:1 to images, not fragments of images

If future use cases require fine-grained image region vectors (e.g., "this region of a diagram"), that would warrant a separate `image_region_vdb` — not a change to per-image granularity.

### DD-2: Vision embedding dimension is independent of text embedding dimension

The text embedding model (`text-embedding-v3`) produces 1024-dimensional vectors. Vision models have their own dimensions:
- CLIP ViT-L/14: 768d
- CLIP ViT-B/32: 512d
- SigLIP: 768d
- DINOv2 ViT-g: 1536d

The `image_vision_vdb` must accept a dimension from the configured vision embedding function, not inherit 1024 from the text embedding model. This is implemented by passing `vision_embedding_dim` through the `global_config` dict (the same mechanism that carries `working_dir`, `embedding_batch_num`, etc. to all storage instances).

### DD-3: Content-hash deduplication (SHA-256 of raw image bytes)

When the same image appears in multiple documents (e.g., a logo repeated across a report), computing a vision vector for each occurrence wastes compute and storage. Instead:

- Compute `content_hash = sha256(image_bytes).hexdigest()`
- Before embedding, check if `content_hash` already exists in `image_vision_vdb`
- **If found**: Skip embedding. Add a lightweight cross-reference record (in a companion KV store `image_vision_usage`) mapping `content_hash → [(source_doc_id, chunk_id, file_path)]`
- **If not found**: Embed and upsert

The companion KV store `image_vision_usage` (a `JsonKVStorage` instance with namespace `"image_vision_usage"`) tracks which documents reference each vision vector. This enables:
- Accurate deletion: remove a vision vector only when its last referencing document is deleted
- Citation tracing: show which documents contain a given image
- Audit trail: track image reuse across the KB

### DD-4: Vision vectors stored as raw float16 (no compression)

The existing VDBs compress text vectors via `float16 → zlib → base64` (in `nano_vector_db_impl.py:132-134`). This adds CPU overhead on every read (decompress) and write (compress).

For `image_vision_vdb`, the vector count is orders of magnitude smaller than text chunk vectors (hundreds to low thousands of images vs. potentially hundreds of thousands of text chunks). The space savings of compression are negligible at this scale, and uncompressed storage enables zero-copy reads for vision similarity search. The `NanoVectorDBStorage` class already supports raw float16 numpy storage — this just omits the compression step at initialization time via a `compress_vector` flag in `vector_db_storage_cls_kwargs`.

### DD-5: Optional (graceful degradation when no vision embedding function is provided)

If `VISION_EMBEDDING_MODEL` is not configured (env var unset or empty), `image_vision_vdb` is not created. The system operates identically to today — VLM captioning + text-only embedding. No migration, no schema change, no error.

This is implemented by a conditional in the storage initialization:
```python
if self.vision_embedding_func is not None:
    self.image_vision_vdb = self.vector_db_storage_cls(
        namespace="image_vision",
        workspace=self.workspace,
        embedding_func=self.vision_embedding_func,
        meta_fields={"content_hash", "img_path", "source_doc_id",
                      "chunk_id", "entity_name", "file_path", "kb_name"},
        vector_db_storage_cls_kwargs={"compress_vector": False},
    )
```

### DD-6: Follow existing Naming Convention

| Component | Namespace | File | VDB Attribute |
|-----------|-----------|------|---------------|
| Text chunks | `"chunks"` | `vdb_chunks.json` | `chunks_vdb` |
| Entities | `"entities"` | `vdb_entities.json` | `entities_vdb` |
| Relationships | `"relationships"` | `vdb_relationships.json` | `relationships_vdb` |
| **Image vision** | `"image_vision"` | `vdb_image_vision.json` | `image_vision_vdb` |

The namespace constant `VECTOR_STORE_IMAGE_VISION = "image_vision"` is added to LightRAG's `namespace.py` alongside the existing constants.

## Data Lifecycle

### Create
1. During `RAGAnything.process_document_complete()`, after `ImageModalProcessor.generate_description_only()` returns the VLM caption
2. Read image bytes from `img_path`
3. Compute `content_hash = sha256(image_bytes)`
4. Check `image_vision_vdb` for existing `content_hash`:
   - **Exists**: Record `(content_hash, source_doc_id, chunk_id)` in `image_vision_usage` KV
   - **Does not exist**: Call `vision_embedding_func(image_bytes)` → upsert to `image_vision_vdb` with all metadata fields → record usage in `image_vision_usage`
5. On `index_done_callback()`: persist both `image_vision_vdb` and `image_vision_usage` to disk
6. Set cross-process update flag for `image_vision` namespace (same mechanism as other VDBs)

### Query
1. **Vision-to-vision**: Accept query image → embed via `vision_embedding_func` → `image_vision_vdb.query(query_vector, top_k=N)` → return results with metadata
2. **Text-to-vision** (if model supports): Accept text query → embed via `vision_embedding_func` (text mode) → `image_vision_vdb.query()` → return semantically related images
3. **Metadata filter**: Query with filter on `kb_name`, `source_doc_id`, or `entity_name` to scope results

### Update
1. If a document is re-processed (new version uploaded): images with unchanged `content_hash` are skipped (dedup hit). New or changed images are embedded and upserted.
2. If the vision embedding model is changed: all vectors must be recomputed. This is triggered by a `vision_model_hash` field stored alongside each vector — if the configured model's hash doesn't match, vectors are re-embedded on next access (lazy migration).

### Delete
1. **Document deletion**: `adelete_by_doc_id(full_id)` → query `image_vision_usage` for all `content_hash` entries where `source_doc_id == full_id` → for each hash, remove the usage record → if usage count reaches zero, call `image_vision_vdb.delete([vector_id])` → finalize both stores → invalidate query cache
2. **KB deletion**: `shutil.rmtree(kb_dir(name))` wipes `vdb_image_vision.json` and `kv_store_image_vision_usage.json` along with all other storage files — no special handling needed

## Integration Points

### 1. LightRAG Storage Layer (`lightrag.py`)

The `__post_init__` method gains a conditional block (after `relationships_vdb` at line 723):

```python
# Existing (lines 712-729):
self.entities_vdb = self.vector_db_storage_cls(
    namespace=NameSpace.VECTOR_STORE_ENTITIES, ...)
self.relationships_vdb = self.vector_db_storage_cls(
    namespace=NameSpace.VECTOR_STORE_RELATIONSHIPS, ...)
self.chunks_vdb = self.vector_db_storage_cls(
    namespace=NameSpace.VECTOR_STORE_CHUNKS, ...)

# NEW:
if self.vision_embedding_func is not None:
    self.image_vision_vdb = self.vector_db_storage_cls(
        namespace=NameSpace.VECTOR_STORE_IMAGE_VISION,
        workspace=self.workspace,
        embedding_func=self.vision_embedding_func,
        meta_fields={"content_hash", "img_path", "source_doc_id",
                      "chunk_id", "entity_name", "file_path", "kb_name"},
        vector_db_storage_cls_kwargs={"compress_vector": False},
    )
    self.image_vision_usage = self.key_string_value_json_storage_cls(
        namespace=NameSpace.KV_STORE_IMAGE_VISION_USAGE,
        workspace=self.workspace,
    )
```

### 2. Document Processing Pipeline (`multimodal_processor.py`)

After `ImageModalProcessor.generate_description_only()` returns (line ~554 in `_process_multimodal_content_batch_type_aware`), insert the vision embedding step:

```python
if self.image_vision_vdb is not None and item_type == "image":
    await self._embed_and_store_image_vision(
        img_path=processed_item["img_path"],
        content_hash=processed_item["content_hash"],
        source_doc_id=doc_id,
        chunk_id=processed_item["chunk_id"],
        entity_name=processed_item.get("entity_name"),
        file_path=processed_item.get("file_path"),
    )
```

### 3. Document Deletion (`knowledge.py` + `lightrag.py`)

The existing `adelete_by_doc_id()` cascades through `chunks_vdb`, `entities_vdb`, `relationships_vdb`, KV stores, and the graph. Add:

```python
# In adelete_by_doc_id(), after entity/relation cleanup (~line 3930):
if hasattr(self, 'image_vision_vdb') and self.image_vision_vdb is not None:
    await self._delete_image_vision_by_doc_id(doc_id)
```

The `_delete_image_vision_by_doc_id()` method:
1. Query `image_vision_usage` for all `content_hash` entries matching `source_doc_id`
2. For each hash, decrement/remove the usage record
3. If usage count for a hash reaches zero, delete from `image_vision_vdb`
4. Index done callback on both stores

### 4. KB Deletion (`knowledge.py`)

No code change required. `shutil.rmtree(kb_dir(name))` at line 1058 already wipes the entire KB directory including any new files. The `finalize_storages()` call at line 1006 naturally covers the new stores when they exist.

### 5. Query Pipeline (`pipeline.py`)

A new query method `aquery_vision()` accepts an image path (or `image_data` bytes):

```python
async def aquery_vision(self, query_image: bytes | str, top_k: int = 10,
                        kb_name: str | None = None):
    vision_vector = await self.vision_embedding_func([query_image])
    results = await self.image_vision_vdb.query(
        query=vision_vector[0],
        top_k=top_k,
        better_than_threshold=0.7,  # Higher threshold for visual similarity
    )
    return results
```

### 6. Cross-Process Safety

The new VDB inherits all existing safety mechanisms with zero additional configuration:
- **Namespace lock**: `get_namespace_lock("image_vision", workspace)` is called automatically by `NanoVectorDBStorage._get_client()`
- **Update flag**: Set by `index_done_callback()` → `set_all_update_flags("image_vision")` → checked by `_get_client()` on next access
- **Per-KB serial queue**: Uploads to the same KB are serialized, preventing concurrent writes
- **File lock**: Subprocess workers acquire OS-level `FileLock` before writing
- **Staleness detection**: `get_kb()` checks `kv_store_doc_status.json` mtime, which is touched when any storage changes — including the new stores

## Risks and Mitigations

### Risk 1: Vision embedding model availability
**Severity**: Low. **Mitigation**: The entire feature is gated by `VISION_EMBEDDING_MODEL` configuration. If unset, no `image_vision_vdb` is created and the system operates identically to today. No runtime dependency on a vision embedding service unless explicitly configured.

### Risk 2: Vision embedding model dimension mismatch on hot-reload
**Severity**: Medium. If an admin changes `VISION_EMBEDDING_MODEL` between processing runs, existing vectors have the old dimension but new vectors have the new dimension. NanoVectorDB enforces fixed dimension — this would cause a crash on upsert.
**Mitigation**: Store a `vision_model_hash` in the VDB metadata (a sentinel entry with `__id__ = "__vision_model_config__"`). On initialization, compare the stored hash against the current model config. On mismatch, either:
- (a) Auto-drop and re-embed all images (lazy, on next document access)
- (b) Refuse to start with a clear error message and migration instructions
- **Choice: (b) for safety.** Re-embedding is a data-mutating operation that should be explicit. The error message guides the admin to either delete the KB and re-ingest, or run a migration script.

### Risk 3: Disk space for uncompressed vectors
**Severity**: Low. For a KB with 10,000 unique images at 768d float16: 10,000 images x 768 floats x 2 bytes/float = ~15MB of vector data. Plus NanoVectorDB metadata overhead (~200 bytes/entry) = ~2MB. Total: ~17MB for 10,000 images. Even at 100,000 images: ~170MB. This is negligible compared to the image files themselves.

### Risk 4: `content_hash` collision with non-identical images
**Severity**: Negligible. SHA-256 has a collision probability of ~1 in 2^128 (birthday bound). For context, the system would need to process ~4 billion images before reaching a 50% collision probability.

### Risk 5: Orphaned usage records
**Severity**: Low. If a process crashes between writing `image_vision_vdb` and writing `image_vision_usage`, the usage KV may not reflect the actual content. **Mitigation**: A startup integrity check (same pattern as the existing `_stuck_recovery_loop` in `kb_service.py`) compares `image_vision_vdb` IDs against `image_vision_usage` entries and removes orphaned records. This can run as part of the existing queue drain on startup.

## Migration Path

### Phase 1: Add storage infrastructure (non-breaking)
1. Add `VECTOR_STORE_IMAGE_VISION` and `KV_STORE_IMAGE_VISION_USAGE` constants to LightRAG `namespace.py`
2. Add conditional `image_vision_vdb` + `image_vision_usage` initialization in `LightRAG.__post_init__()` — gated by `vision_embedding_func is not None`
3. Add `vision_embedding_func` parameter to `RAGAnythingConfig` and factory
4. Add orphan cleanup to startup integrity check

**At this point**: No behavior change. Existing KBs work identically. The VDB is only created for new KBs with `VISION_EMBEDDING_MODEL` configured.

### Phase 2: Add ingestion integration (non-breaking)
1. Add `_embed_and_store_image_vision()` method to `EmbedProcessorMixin`
2. Call it from `_process_multimodal_content_batch_type_aware()` after image processing
3. Add cascade delete logic to `adelete_by_doc_id()`
4. Add `vision_model_hash` sentinel entry for dimension-change detection

**At this point**: Newly processed documents populate `image_vision_vdb`. Queries still use text-only retrieval. Existing KBs are unchanged.

### Phase 3: Add query integration (feature flag)
1. Add `aquery_vision()` method to `QueryMixin`
2. Add `query_mode="vision"` option behind a feature flag
3. Add RRF fusion logic for hybrid text+vision queries

**At this point**: Full vision search capability available. Feature flag allows gradual rollout.

### Phase 4: Backfill tool (optional, manual)
A CLI script `scripts/backfill_vision_vectors.py` that:
1. Reads all image paths from existing KB `text_chunks` KV (filter `is_multimodal=True, original_type="image"`)
2. Computes `content_hash` for each image
3. Embeds and upserts to `image_vision_vdb`
4. Populates `image_vision_usage`

This is a manual, admin-triggered operation — never automatic — because it incurs embedding API costs and modifies existing KB data.

### Rollback
At any phase, setting `VISION_EMBEDDING_MODEL=""` (empty) and restarting the server disables the feature. Existing `vdb_image_vision.json` files on disk are ignored (not loaded) when `vision_embedding_func` is None. No data is lost — text-based retrieval continues to work.

## Consequences

### What becomes easier
- **Visual similarity search**: Query-by-image becomes a first-class operation
- **Cross-modal retrieval**: "Find text about images that look like this" can fuse vision and text vector results
- **Image deduplication across documents**: `content_hash` naturally identifies duplicate images across the entire KB, enabling an "image reuse" audit view
- **Future modality vector stores**: The pattern established here (conditional VDB creation, companion usage KV, cascade deletion, dimension-change sentinel) is directly reusable for `video_keyframe_vdb`, `audio_spectrogram_vdb`, etc.
- **Vision embedding model experimentation**: The independent dimension means admins can switch vision models without affecting text embedding quality

### What becomes harder
- **KB portability**: Copying a KB directory now must also copy `vdb_image_vision.json` and `kv_store_image_vision_usage.json` (but this is true of all storage files — the directory is already the unit of portability)
- **Storage initialization time**: One or two additional files to load on KB initialization (negligible — NanoVectorDB loads via memory-mapped I/O)
- **Document deletion latency**: One additional store to cascade-delete from (adds ~tens of milliseconds for usage-count queries)
- **Cross-process coordination surface**: One more namespace lock and update flag in the shared storage module (but these follow the exact same pattern as the existing three VDBs — no new mechanism, just one more instance of a proven pattern)
- **Testing surface**: Vision embedding function must be mockable in tests; integration tests need a test fixture that provides a dummy vision embedding function (e.g., random 768d vectors). The existing test infrastructure for `chunks_vdb` serves as a template.
