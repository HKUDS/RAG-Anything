## MODIFIED Requirements

### Requirement: 邻居遍历检索

系统 SHALL 从匹配到的实体节点出发，沿知识图谱边遍历 1-2 跳邻居节点，召回邻居实体关联的文档 chunk。当关联 chunk 通过 `text_chunks_db` 批量接口无法解析时，SHALL 自动触发单条 fallback 读取。

#### Scenario: 1 跳邻居遍历
- **WHEN** 匹配到实体 "张三" 且 `GRAPH_DEPTH=1`
- **THEN** 系统遍历 "张三" 的 1 跳邻居（如 "技术部"、"项目A"）
- **THEN** 返回 "张三" 及其 1 跳邻居关联的所有 chunk
- **THEN** 若 `get_by_ids()` 对遍历结果的 chunk ID 全部返回 None，触发单条 fallback

#### Scenario: 实体未匹配
- **WHEN** 查询中的实体在知识图谱中不存在
- **THEN** 图谱通道返回空结果列表
- **THEN** 不影响其他通道检索

## ADDED Requirements

### Requirement: 实体关联 Chunk 解析验证

在 `_find_related_text_unit_from_entities` 返回结果前，系统 SHALL 验证 chunk 解析结果。若实体有 `source_id` 但关联的所有 chunk ID 均无法解析，系统 SHALL 记录 WARNING 日志并返回空结果，同时将失败的 chunk ID 样本写入日志。

#### Scenario: 全部 chunk ID 解析失败
- **WHEN** 实体的 `source_id` 包含 5 个 chunk ID 但 `get_by_ids()` 对全部 5 个返回 None
- **THEN** 在单条 fallback 也失败后，返回空结果
- **THEN** 日志输出 WARNING: `All {N} chunk IDs from entity source_id failed to resolve. Sample IDs: [id1, id2, id3]`
