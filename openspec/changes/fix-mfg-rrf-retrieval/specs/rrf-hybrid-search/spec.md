# RRF Hybrid Search (Delta)

## MODIFIED Requirements

### Requirement: Graph channel entity matching
Graph 通道 SHALL 使用 NetworkXStorage 的 async API 进行实体匹配：`await graph.get_all_nodes()` 获取所有节点，`await graph.node_degree(id)` 获取节点度数。

#### Scenario: 实体匹配正常执行
- **WHEN** RRF 搜索启用 graph 通道
- **THEN** 系统 SHALL 正确 await 所有 NetworkXStorage async 方法，返回匹配的实体列表

#### Scenario: 实体匹配失败降级
- **WHEN** entity matching 抛出异常
- **THEN** 系统 SHALL 记录 warning 日志并返回空列表，不影响其他通道

### Requirement: Graph channel neighbor traversal
Graph 通道 SHALL 使用 `await graph.get_node(id)` 和 `await graph.get_node_edges(id)` 进行 BFS 邻居遍历。

#### Scenario: 邻居遍历正常执行
- **WHEN** 实体匹配返回非空结果
- **THEN** 系统 SHALL 通过 `await graph.get_node_edges` 遍历邻居节点，返回带距离衰减权重的 chunk 列表

### Requirement: Vector channel uses naive mode
Vector 通道 SHALL 使用 LightRAG 的 `mode="naive"` 进行 chunk 向量直接相似度搜索，而非 `mode="local"` 的实体优先搜索。

#### Scenario: Naive mode chunk retrieval
- **WHEN** RRF 搜索启用 vector 通道
- **THEN** 系统 SHALL 调用 `LightRAG.aquery(query, QueryParam(mode="naive", only_need_context=True, top_k=100))` 获取 raw chunks

#### Scenario: Vector channel returns non-empty for small KB
- **WHEN** 知识库中仅有 4 个 chunk 且查询词与其中 1 个 chunk 高度相关
- **THEN** vector 通道 SHALL 返回至少 1 个 chunk（不再因实体质量导致 0 chunks）

### Requirement: RRF context debug logging
RRF 查询 SHALL 在 INFO 级别记录 top-3 检索结果的 chunk_id 和内容前 100 字符，便于诊断 context 传递链路。

#### Scenario: Debug log for retrieved context
- **WHEN** RRF 检索完成并准备传给 LLM
- **THEN** 日志 SHALL 包含每条 top-3 chunk 的 chunk_id 和内容摘要

## REMOVED Requirements

### Requirement: Graph channel uses synchronous run_in_executor
**Reason**: NetworkXStorage 方法在 lightrag-hku>=1.3 中全部为 async，不再需要 run_in_executor 包装。
**Migration**: `_graph_search` 直接 `await self._graph.search(query, top_k)`。
