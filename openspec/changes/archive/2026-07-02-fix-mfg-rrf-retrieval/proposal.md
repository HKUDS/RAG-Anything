## Why

制造智能体的 RRF 三路融合检索引擎在检索召回率上显著低于普通智能体所用的 LightRAG 原生 hybrid 查询。同一知识库中，LightRAG 原生查询能正确检索到的内容，制造智能体 RRF 引擎却报"参考资料中未找到相关信息"。根因是 RRF 三个通道各有缺陷，且小语料库下问题叠加放大。

## What Changes

- **BM25 通道修复**：移除 `scores <= 0` 过滤条件，允许 BM25 负分/零分结果进入 RRF 融合（小语料库下 IDF 公式产生负值是正常行为）
- **Graph 通道修复**：将所有 `NetworkXStorage` API 调用改为 async/await（`get_all_nodes`、`get_node`、`get_node_edges`、`get_all_edges`、`node_degree` 在 lightrag-hku>=1.3 中均为异步方法）
- **Vector 通道修复**：将查询模式从 `mode="local"`（实体优先）改为 `mode="naive"`（chunk 向量直接相似度），避免实体提取质量差导致 chunk 召回断裂
- **RRF→LLM Context 传递验证**：在 `_aquery_rrf` 中增加 debug 日志，确保检索到的 chunk 正确传入 LLM prompt

## Capabilities

### Modified Capabilities
- `rrf-hybrid-search`: BM25 分数过滤条件、GraphRetriever 异步适配、Vector 通道查询模式、Context 传递链路
- `bm25-keyword-index`: BM25 分数阈值从 `<= 0` 改为不过滤（让 RRF rank 排序决定）

## Impact

- `raganything/hybrid_search.py` — BM25IndexManager.search、GraphRetriever（全部方法改为 async）、HybridSearchEngine._vector_search、HybridSearchEngine._graph_search、HybridSearchEngine.get_subgraph
