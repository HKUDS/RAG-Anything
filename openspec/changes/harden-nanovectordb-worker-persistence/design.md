## Context

The Worker holds a knowledge-base file lock while parsing, embedding, and
finalizing a document. In production, LightRAG's NanoVectorDB `chunks_vdb`
contains newly embedded vectors in memory, but its `index_done_callback()` can
return `False` after observing a stale cross-process update flag. The current
finalizer ignores that return value, completes graph processing, and lets later
automatic tagging discover zero durable vectors.

## Goals / Non-Goals

**Goals:**
- Persist Worker-owned NanoVectorDB data while the knowledge-base processing
  lock is held.
- Verify the persistence callback succeeds and propagate a failure to the
  Worker lifecycle.
- Preserve existing PG-backed KV/doc-status and NetworkX finalization.

**Non-Goals:**
- Do not change vector model providers, the visual embedding credential, or
  vector backend selection.
- Do not merge or repair existing zero-vector documents automatically.
- Do not bypass the knowledge-base processing lock or weaken concurrent-write
  protection.

## Decisions

### Clear only stale self-update flags during locked Worker finalization

Before persisting a NanoVectorDB store, the Worker will clear its own
`storage_updated` flag only while it owns the existing knowledge-base lock.
This permits the in-memory vectors produced by that Worker to be saved instead
of reloading an earlier empty file. The finalizer will not clear flags for
arbitrary non-NanoVectorDB stores.

Calling the vendor callback unchanged is insufficient because `False` is a
normal return value for its reload branch and the current caller ignores it.
Forcing `client.save()` directly is rejected because it bypasses the storage
lock and update notifications implemented by LightRAG.

### Retire the pre-Worker cache without persisting file-backed VDBs

After a Worker exits, the service invalidates any KB core that was loaded
before the Worker started. That core is a separate process snapshot and can
still contain an empty NanoVectorDB. Its retirement therefore accepts an
explicit `persist_vector_stores=False` mode: it still finalizes KV, parse,
multimodal, and vendor resources, but skips the three file-backed VDB
callbacks. Ordinary LRU eviction and normal shutdown retain the default
`True` behavior.

### Make persistence callback failure terminal

The finalizer will raise a bounded runtime error when a vector-store callback
returns `False` or raises. The existing Worker failure path then prevents a
successful completion status and exposes the persistence problem for retry or
operator diagnosis.

## Risks / Trade-offs

- [A second writer bypasses the KB lock] -> Existing process lock remains the
  authority; this change does not make unsafe concurrent writers safe.
- [Vendor storage internals change] -> Detect NanoVectorDB by the documented
  `storage_updated` attribute and limit the behavior to VDB stores.
- [Persistence failure after text rows exist] -> Worker reports failure rather
  than allowing automatic tagging to operate on an incomplete document.

## Migration Plan

1. Rebuild and restart `app`; no database migration is required.
2. Upload a small text-only PDF with image/table/equation processing disabled.
3. Confirm the KB-specific nested `vdb_chunks.json` has entries, automatic
   tagging succeeds, and the Worker does not report a persistence failure.
4. Roll back by restoring the previous image; existing persisted vectors remain
   unchanged.
