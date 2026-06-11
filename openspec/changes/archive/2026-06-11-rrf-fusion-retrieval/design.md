## Context

RAG-Anything 当前通过 LightRAG 内置的 `hybrid` 模式进行检索，该模式在 LightRAG 内部做简单的 local+global 混合，未显式拆分为独立的多通道检索。实际检索场景中，BM25 关键词匹配、向量语义相似度和知识图谱实体关系各有独到优势，单独依赖任一通道都会丢失其他维度的信号。业界标准做法是通过 Reciprocal Rank Fusion (RRF) 将多通道独立检索结果按排名融合，已在 BEIR 等基准中验证 Hit Rate 可提升 50%+。

当前 `raganything/query.py` 中的所有查询方法直接调用 `self.lightrag.aquery()` 并将 `mode` 参数透传给 LightRAG。本次设计在 LightRAG 上层新增 `HybridSearchEngine`，作为可插拔的检索中间层，不影响现有 LightRAG 查询管线。

## Goals / Non-Goals

**Goals:**
- 实现 BM25 关键词、向量语义、知识图谱三路独立并行检索
- 实现 RRF 公式融合排序：`RRF_score(d) = Σ 1/(k + rank_i(d))`, k=60
- 在 `RAGAnything.aquery()` 中集成新的 `rrf` 模式，与现有模式并存
- BM25 索引支持文档入库时增量更新
- 三路检索并行执行，P95 延迟 < 200ms
- 通过环境变量暴露所有可调参数

**Non-Goals:**
- 不修改 LightRAG 内部检索逻辑
- 不实现自定义向量索引（复用 LightRAG 已有的 HNSW 向量存储）
- 不构建独立的图数据库（复用 LightRAG 已有的 NetworkX 图存储）
- 不实现跨知识库的联合检索（单次查询针对单个知识库）
- 不做查询缓存（缓存属于独立功能）

## Decisions

### Decision 1: 独立模块 vs 修改 query.py

**选择**: 新建 `raganything/hybrid_search.py` 独立模块，通过依赖注入集成到 `QueryMixin`。

**备选**: 直接在 `query.py` 中添加融合检索方法。

**理由**: 独立模块保持单一职责，便于单独测试和未来替换。`HybridSearchEngine` 作为可插拔组件，接收 LightRAG 实例引用即可工作，耦合度低。`query.py` 已近 1000 行，继续膨胀会难以维护。

### Decision 2: 向量和图的检索实现策略

**选择**: 复用 LightRAG 已有存储层（HNSW 向量索引 + NetworkX 知识图谱），通过 LightRAG 的内部 API 发起检索。

**备选**: 自己维护独立的向量索引和图数据库。

**理由**: LightRAG 已在入库时构建了向量和图索引，重复构建会浪费存储和计算。直接调用 LightRAG 的内部检索方法（如 `lightrag.chunk_entity_relation_graph` 和向量存储查询），避免索引不一致问题。

### Decision 3: BM25 索引存储与更新策略

**选择**: 使用 `rank-bm25` 的 `BM25Okapi` 类，在内存中维护索引；文档入库时异步触发索引重建。

**备选**: 持久化 BM25 索引到磁盘。

**理由**: BM25Okapi 对中等规模（<10 万文档）在内存中足够高效，重建速度 < 1s。持久化索引增加复杂度而收益有限。未来文档量超过 10 万时可扩展为基于 SQLite FTS5 或 Elasticsearch 的方案。

### Decision 4: RRF 参数 k 的选择

**选择**: k=60（标准值），同时通过 `RRF_K` 环境变量可配置。

**理由**: k=60 是 RRF 原论文和 TREC 社区验证的最优默认值。较小的 k 值（如 k=0）等同于只依赖排名而忽略通道差异，较大的 k 值（如 k=∞）等同于等权重平均。60 在大多数场景下提供了最佳的排名平衡。

### Decision 5: 通道权重控制

**选择**: 在各通道的 top_k 上控制权重（保留更多高质量通道的候选项），而非在 RRF 公式中加权。

**备选**: 在 RRF 公式中乘以通道权重 `w_i/(k+rank_i)`。

**理由**: 通过 top_k 控制通道影响力更直观且可解释。BM25(top_k=50)、向量(top_k=100)、图谱(top_k=30) 的比例设置已经反映了各通道的置信度。在公式中再加权会过度参数化，增加调优难度而实测收益微弱。

## Risks / Trade-offs

- **[BM25 对中文分词敏感]** → Mitigation: 使用 jieba 分词作为 BM25 tokenizer，配合 `rank-bm25` 的分词接口。提供 `BM25_TOKENIZER` 环境变量支持自定义分词器。

- **[向量和图通道依赖 LightRAG 内部 API]** → Mitigation: 通过 try/except 捕获 API 变更，降级为仅使用可用通道。记录警告日志便于排查。锁定 LightRAG 最小版本。

- **[三路并行增加内存占用]** → Trade-off: BM25 索引 + 向量索引 + 图谱同时驻留内存。单知识库（1 万文档）预估额外内存 ~200MB。可通过 `RRF_ENABLED_CHANNELS` 环境变量禁用不需要的通道。

- **[入库时重建 BM25 索引的延迟]** → Mitigation: 异步后台任务重建索引，不阻塞 API 响应。重建期间查询使用旧索引，重建完成后原子替换。

- **[P95 < 200ms 的延迟目标依赖三路并行]** → Trade-off: 如果某通道异常慢（如图遍历深），会拖慢整体。通过 `asyncio.wait_for()` 设置单通道 150ms 超时，超时通道结果不参与融合但也不阻塞。
