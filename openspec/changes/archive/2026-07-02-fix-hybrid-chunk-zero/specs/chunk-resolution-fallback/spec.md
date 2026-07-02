## ADDED Requirements

### Requirement: Chunk ID 批量解析失败时单条 fallback

当 `text_chunks_db.get_by_ids(chunk_ids)` 对所有输入的 chunk ID 返回 `None` 或空结果时，系统 SHALL 自动触发单条 fallback：对每个 chunk ID 逐一调用 `text_chunks_db.get_by_id(chunk_id)`，收集成功取回的数据作为降级结果。

#### Scenario: 批量接口全量失败
- **WHEN** `_find_related_text_unit_from_entities` 调用 `get_by_ids(selected_chunk_ids)` 且返回的 `chunk_data_list` 中所有条目均为 `None`
- **THEN** 系统自动进入单条 fallback 模式
- **THEN** 遍历 `selected_chunk_ids`，对每个 ID 调用 `get_by_id(chunk_id)`
- **THEN** 成功取回的 chunk 数据构建为 `result_chunks` 返回
- **THEN** 记录日志：成功/失败数量

#### Scenario: 批量接口部分成功时不触发
- **WHEN** `get_by_ids(selected_chunk_ids)` 至少有一个条目返回有效 chunk 数据
- **THEN** 系统不触发单条 fallback
- **THEN** 使用批量接口返回的数据构建结果
- **THEN** 跳过 None 条目（现有行为不变）

#### Scenario: 关系关联 chunk 的 fallback
- **WHEN** `_find_related_text_unit_from_relations` 中 `get_by_ids()` 全部返回 `None`
- **THEN** 同样触发单条 fallback 模式
- **THEN** 行为与实体 chunk fallback 一致

### Requirement: Chunk 解析结果统计

系统 SHALL 在每次 chunk 解析完成后输出结构化统计日志，包含选中总数、成功解析数、失败解析数及失败 ID 样本。

#### Scenario: 成功解析统计
- **WHEN** `_find_related_text_unit_from_entities` 完成 chunk 解析
- **THEN** 日志输出 `Chunk resolution: {total} IDs selected, {success} resolved, {fail} not found`
- **THEN** 若 `fail > 0`，额外输出 WARNING 级别日志包含最多 3 个失败 ID 样本
- **THEN** 60 秒内相同失败模式的日志去重，避免刷屏

#### Scenario: 全部成功时只输出 info 日志
- **WHEN** 所有 selected_chunk_ids 在 `text_chunks_db` 中成功解析
- **THEN** 日志级别为 INFO，不输出 WARNING
