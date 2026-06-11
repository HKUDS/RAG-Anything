## 1. 模块创建与依赖

- [x] 1.1 确认 `rank-bm25` 已在 `requirements.txt` 中（或安装）
- [x] 1.2 创建 `raganything/hybrid_search.py` 骨架文件，包含类定义和 docstring
- [x] 1.3 定义 `ScoredChunk` 数据类（`chunk_id`, `content`, `score`, `sources`）

## 2. BM25 关键词索引

- [x] 2.1 实现 `BM25IndexManager` 类：`build_index(chunks)`, `search(query, top_k)`, `tokenize(text)`
- [x] 2.2 集成 jieba 分词器作为默认 tokenizer，支持 `BM25_TOKENIZER` 环境变量切换
- [x] 2.3 实现 `rebuild_index_async()` 异步重建 + 原子引用替换（旧索引继续服务）
- [x] 2.4 实现 `update_index_incremental(new_chunks)` 增量更新入口
- [x] 2.5 读取 `BM25_K1`, `BM25_B`, `BM25_TOP_K` 环境变量进行参数配置

## 3. 图谱检索通道

- [x] 3.1 实现 `GraphRetriever` 类：接收 LightRAG 实例引用
- [x] 3.2 实现 `_match_entities(query)` — 从查询文本提取实体并在 LightRAG 图谱中匹配
- [x] 3.3 实现 `_traverse_neighbors(matched_entities, depth)` — 1-N 跳邻居遍历，距离加权
- [x] 3.4 实现 `search(query, top_k)` — 完整图谱检索流程
- [x] 3.5 实现 `get_subgraph(entity_ids)` — 返回 {nodes, edges} 供前端可视化
- [x] 3.6 读取 `GRAPH_DEPTH`, `GRAPH_TOP_K` 环境变量配置

## 4. RRF 融合引擎

- [x] 4.1 实现 `HybridSearchEngine` 类：聚合 BM25IndexManager + GraphRetriever + LightRAG 向量检索
- [x] 4.2 实现 `_vector_search(query, top_k)` — 调用 LightRAG 内部向量检索 API
- [x] 4.3 实现 `_bm25_search(query, top_k)` — 委托 BM25IndexManager
- [x] 4.4 实现 `_graph_search(query, top_k)` — 委托 GraphRetriever
- [x] 4.5 实现 `_rrf_fuse(results: List[List[ScoredChunk]], k: int)` — RRF 公式融合 + 去重 + 排序
- [x] 4.6 实现 `async search(query, top_k, channels)` — 三路并行入口，`asyncio.gather` + 每路超时 150ms
- [x] 4.7 实现降级逻辑：部分通道失败时用剩余通道继续融合，全部失败返回空结果
- [x] 4.8 读取 `RRF_K`, `VECTOR_TOP_K`, `RRF_ENABLED_CHANNELS` 环境变量

## 5. 查询管线集成

- [x] 5.1 在 `RAGAnything._ensure_lightrag_initialized()` 中初始化 `HybridSearchEngine` 实例
- [x] 5.2 在 `QueryMixin.aquery()` 中新增 `mode="rrf"` 分支，调用 `HybridSearchEngine.search()`
- [x] 5.3 在 `QueryMixin.aquery_with_multimodal()` 中同步支持 `mode="rrf"`
- [x] 5.4 在 `ProcessorMixin` 文档入库流程末尾触发 `BM25IndexManager.rebuild_index_async()`
- [x] 5.5 批量入库防抖：合并 500ms 内的多次入库为单次索引重建

## 6. 服务端配置暴露

- [x] 6.1 在 `server.py` 的 `/api/settings` 响应中添加 RRF 相关配置项
- [x] 6.2 在 `.env` 中添加所有新环境变量及默认值
- [x] 6.3 在查询 API 端点中确保 `mode=rrf` 被正确传递（已有通过机制）

## 7. 测试

- [x] 7.1 编写 `tests/test_hybrid_search.py`：BM25 索引构建与检索单元测试
- [x] 7.2 编写 RRF 融合算法单元测试（验证公式计算正确性、去重、排序）
- [x] 7.3 编写图谱检索通道单元测试（实体匹配 + 邻居遍历）
- [x] 7.4 编写三路融合集成测试（模拟完整查询管线）
- [x] 7.5 编写降级场景测试（单通道失败、全部超时）
- [x] 7.6 在测试文件中内置 fixtures（`sample_chunks`, `bm25_manager`）
