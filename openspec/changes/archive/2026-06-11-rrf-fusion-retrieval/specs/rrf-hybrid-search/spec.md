## ADDED Requirements

### Requirement: RRF 三路融合检索入口

系统 SHALL 在 `RAGAnything.aquery()` 中提供 `mode="rrf"` 检索模式，该模式调用 `HybridSearchEngine` 执行三路并行检索并通过 RRF 公式融合排序后返回结果。

#### Scenario: 基本 RRF 检索流程
- **WHEN** 用户调用 `aquery("年假政策", mode="rrf")`
- **THEN** 系统并行执行 BM25、向量、图谱三路检索
- **THEN** 各路返回 top_k 候选后通过 `RRF_score = Σ 1/(60 + rank_i)` 融合
- **THEN** 返回按 RRF 分数降序排列的检索结果列表

#### Scenario: RRF 模式与其他模式并存
- **WHEN** 用户调用 `aquery("测试查询", mode="hybrid")`
- **THEN** 系统仍使用 LightRAG 内置 hybrid 模式，行为不变
- **WHEN** 用户调用 `aquery("测试查询", mode="rrf")`
- **THEN** 系统使用新的 RRF 融合检索引擎

#### Scenario: 部分通道不可用时降级
- **WHEN** 向量检索通道因 LightRAG 内部错误失败
- **THEN** 系统记录警告日志并仅使用 BM25 和图谱通道结果进行 RRF 融合
- **THEN** 不抛出异常，正常返回可用结果

### Requirement: 三路并行检索执行

系统 SHALL 使用 `asyncio.gather()` 并行执行三路检索，每路设置独立超时（默认 150ms），超时通道不被阻塞且不参与融合。

#### Scenario: 并行执行与超时控制
- **WHEN** 三路检索并行发起
- **THEN** 各路检索在各自超时内完成
- **THEN** 超时通道记录警告日志并跳过
- **THEN** 总延迟不超过最慢成功通道的时间 + RRF 融合开销

#### Scenario: 全部通道超时
- **WHEN** 所有三路检索均超时
- **THEN** 系统返回空结果列表并附带错误信息
- **THEN** 不抛出异常

### Requirement: RRF 分数计算与排序

系统 SHALL 对三路检索结果按 `RRF_score(chunk) = Σ 1/(k + rank_i(chunk))` 计算融合分数，其中 k 默认为 60，通过环境变量 `RRF_K` 可配置。同一 chunk 在多路中出现时累加其 RRF 分数。

#### Scenario: 相同 chunk 在多通道命中
- **WHEN** chunk-A 在 BM25 排名为 1、向量排名为 3、图谱中未出现
- **THEN** RRF_score(chunk-A) = 1/(60+1) + 1/(60+3) = 0.0164 + 0.0159 = 0.0323
- **THEN** chunk-A 的最终排名高于仅在单通道命中且排名相同的 chunk-B

#### Scenario: 自定义 k 值
- **WHEN** 环境变量 `RRF_K=10`
- **THEN** RRF 公式使用 k=10 计算分数
- **THEN** 排名差异对分数的区分度更大（小 k 值更强调排名优势）

### Requirement: 检索结果去重与溯源

系统 SHALL 对融合后的结果按 chunk_id 去重，并在每个结果中标注来源通道（sources 字段），用于前端展示和调试。

#### Scenario: 结果带有通道溯源信息
- **WHEN** RRF 融合完成
- **THEN** 每个返回的 `ScoredChunk` 包含 `sources: List[str]` 字段，值可能为 `["bm25"]`, `["vector"]`, `["graph"]` 或它们的组合
- **THEN** `score` 字段为 RRF 融合分数
