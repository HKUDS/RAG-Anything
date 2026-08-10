## ADDED Requirements

### Requirement: 视频片段抽取并发控制

系统 SHALL 在 v2 视频语义分段路径中受控并发执行各片段的实体抽取，并在全部片段完成后保持整文档一次性的图谱合并语义。

#### Scenario: 片段抽取并行执行

- **WHEN** v2 视频包含多个语义片段且 `video_segment_concurrent` 大于 1
- **THEN** 各片段的 `extract_entities` LLM 调用可并发执行
- **THEN** 并发上限受 `video_segment_concurrent` 与 `llm_model_max_async` 共同约束

#### Scenario: 整文档合并保持一次

- **WHEN** 全部片段完成实体抽取
- **THEN** 调用方仅执行一次 `merge_nodes_and_edges`（覆盖所有片段结果）
- **THEN** `full_entities`/`full_relations` 的 `doc_id` 条目包含该文档全部片段的实体与关系

#### Scenario: 抽取结果确定

- **WHEN** 同一视频在相同配置下重试
- **THEN** 抽取结果按片段序号确定性聚合
- **THEN** 图谱节点、`belongs_to` 边与向量记录不因并发完成顺序而改变