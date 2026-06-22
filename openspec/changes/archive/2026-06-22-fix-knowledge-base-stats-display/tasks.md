## 1. Fix stats chunk count aggregation

- [x] 1.1 In `knowledge_stats()`, replace `len(vdb_chunks.json)` with aggregation from `kv_store_doc_status.json` by iterating document entries and summing `chunks_count`
- [x] 1.2 Handle edge case: doc_status file missing or corrupted (use existing `_safe_load_json` pattern)
- [x] 1.3 Verify stats API still returns correct `documents`, `entities`, `relations` fields

## 2. Remove graph endpoint truncation limits

- [x] 2.1 In `graph_data()`, remove `[:40]` slice on `entity_names` iteration (line 430)
- [x] 2.2 In `graph_data()`, remove `[:100]` slice on `relation_pairs` iteration (line 439)
- [x] 2.3 In `graph_data()`, remove `nodes[:120]` and `edges[:80]` return value truncation (line 450)

## 3. Validate fix

- [x] 3.1 Start server and verify `/api/knowledge/stats` returns chunk count matching doc_status aggregate
- [x] 3.2 Verify `/api/knowledge/graph` returns all nodes and edges without artificial limits
- [x] 3.3 Confirm knowledge base page (frontend) displays correct stats and full graph
- [x] 3.4 Verify upload worker (`process_worker.py`) is not affected by changes
