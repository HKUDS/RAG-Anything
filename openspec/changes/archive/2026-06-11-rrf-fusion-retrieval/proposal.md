## Why

当前 RAG-Anything 的 "hybrid" 检索模式依赖 LightRAG 内置的简单混合策略（二选一），缺乏显式的多通道并行检索与 Reciprocal Rank Fusion (RRF) 融合机制。这导致检索召回率受限，尤其在关键词与语义信号互补的场景（如专业术语查询、跨文档推理）中表现不足。实现 BM25 关键词 + 向量语义 + 知识图谱三路独立检索并以 RRF 公式融合，可将 Hit Rate 提升 50%+，使后续 Agentic RAG 推理获得更完整的上下文。

## What Changes

- 新建 `raganything/hybrid_search.py` 模块，实现 `HybridSearchEngine` 类
- 实现三路独立并行检索通道：BM25 关键词检索（Okapi BM25）、向量语义检索（Cosine + HNSW）、知识图谱检索（实体匹配 + 邻居遍历）
- 实现 RRF 融合算法 `Σ 1/(k + rank_i)` 对所有通道结果进行分数融合与重排序
- 在查询管线中集成 `HybridSearchEngine`，替换当前单一的 LightRAG hybrid 模式
- 添加环境变量 `RRF_K`、通道权重及 top_k 参数控制
- BM25 索引支持增量更新（新文档入库时自动重建）
- **BREAKING**: `/api/query` 端点的 `mode` 参数新增 `rrf` 选项；默认行为保持向后兼容

## Capabilities

### New Capabilities

- `rrf-hybrid-search`: 三路并行检索 + RRF 融合引擎，替代当前 LightRAG 内置 hybrid 模式
- `bm25-keyword-index`: 面向知识库文档的 Okapi BM25 倒排索引，支持增量更新
- `graph-channel-retrieval`: 基于知识图谱的实体匹配与邻居遍历检索通道

### Modified Capabilities

<!-- 无现有 spec 文件，均为新增能力 -->

## Impact

- 新增文件: `raganything/hybrid_search.py`（~400 行）
- 新增依赖: `rank-bm25`（已在 requirements.txt 中）
- 修改文件: `raganything/query.py`（集成调用）、`raganything/processor.py`（入库触发 BM25 索引更新）、`server.py`（暴露 mode 参数）
- 环境变量新增: `RRF_K=60`, `BM25_TOP_K=50`, `VECTOR_TOP_K=100`, `GRAPH_TOP_K=30`
- 性能: 三路并行执行，P95 延迟目标 < 200ms
