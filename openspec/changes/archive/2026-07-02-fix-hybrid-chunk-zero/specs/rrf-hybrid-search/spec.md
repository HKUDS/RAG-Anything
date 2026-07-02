## ADDED Requirements

### Requirement: RRF 结果中 chunk 合并后的降级检测

在 RRF 三路融合检索中，当 `_merge_all_chunks` 返回空列表（`merged_chunks=[]`）但实体和关系检索通道均有非空结果时，系统 SHALL 将此视为降级状态并通知下游。

#### Scenario: Chunks 合并为空但实体/关系正常
- **WHEN** RRF 检索完成，`_merge_all_chunks` 返回 `merged_chunks=[]`
- **AND** 实体匹配结果非空且关系遍历结果非空
- **THEN** 在 RAG-Anything 的 `query.py` 中检测到此状态
- **THEN** 在 LLM prompt 中追加降级提示，告知 LLM 回答质量可能下降
- **THEN** 日志输出 `[RRF_DEGRADED] chunks=0 entities={N} relations={M}`

#### Scenario: Chunks 正常时不触发降级
- **WHEN** `merged_chunks` 包含至少 1 个 chunk
- **THEN** 正常构建 LLM prompt，不追加降级提示
- **THEN** 不输出 `[RRF_DEGRADED]` 日志

### Requirement: Chunk 合并前的有效性预检

在 `_merge_all_chunks` 开始合并前，系统 SHALL 对 `vector_chunks`、`entity_chunks`、`relation_chunks` 执行有效性预检，过滤掉 `content` 字段为空或缺失的条目，确保后续 round-robin 合并不产生静默丢失。

#### Scenario: Entity chunks 中存在无效条目
- **WHEN** entity_chunks 中某个 chunk 的 `content` 字段为空字符串或缺失
- **THEN** 该 chunk 在合并前被过滤掉
- **THEN** 日志 DEBUG 级别记录被过滤的 chunk ID

#### Scenario: 所有 chunk 来源均为无效
- **WHEN** vector_chunks、entity_chunks、relation_chunks 经过滤后全部为空
- **THEN** `_merge_all_chunks` 返回空列表
- **THEN** 日志 WARNING 级别输出 `All chunk sources empty after pre-filtering`
