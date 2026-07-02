## 1. BM25: Remove negative score filter

- [x] 1.1 Remove `if scores[idx] <= 0: continue` in `BM25IndexManager.search()` (hybrid_search.py:171)
- [x] 1.2 Verify BM25 returns results for query "PLC 输出信号无响应" on tester KB (4 chunks)

## 2. Graph: Async NetworkXStorage API

- [x] 2.1 Make `_match_entities()` async — await `graph.get_all_nodes()` and `graph.node_degree()`
- [x] 2.2 Make `_traverse_neighbors()` async — await `graph.get_node()` and `graph.get_node_edges()`
- [x] 2.3 Make `search()` async — await `_match_entities()` and `_traverse_neighbors()`
- [x] 2.4 Make `get_subgraph()` async — await all graph method calls
- [x] 2.5 Update `_graph_search()` in HybridSearchEngine to directly await instead of run_in_executor
- [x] 2.6 Update `HybridSearchEngine.get_subgraph()` delegate to async

## 3. Vector: Switch to naive mode

- [x] 3.1 Change `QueryParam(mode="local", ...)` to `QueryParam(mode="naive", ...)` in `_vector_search()`
- [x] 3.2 Verify `only_need_context=True` + `mode="naive"` returns parsable text chunks

## 4. RRF Context Debug Logging

- [x] 4.1 Add INFO log in `_aquery_rrf` printing top-3 retrieved chunk IDs and content[:100]
- [ ] 4.2 Verify log output shows correct chunks for "PLC 输出信号无响应" query

## 5. Integration Test

- [ ] 5.1 Ask "PLC 输出信号无响应" via manufacturing QA — verify answer cites PLC document section 2.2
- [ ] 5.2 Ask "加工精度超差的原因" via manufacturing QA — verify answer cites CNC document section 3.2
- [ ] 5.3 Compare manufacturing QA answer quality against regular agent (LightRAG native) for same query
