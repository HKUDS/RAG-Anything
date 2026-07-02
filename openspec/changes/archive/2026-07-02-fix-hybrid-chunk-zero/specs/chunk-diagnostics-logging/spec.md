## ADDED Requirements

### Requirement: 上下文构建完成时的 chunks=0 告警

当 `_build_context_str` 构建最终上下文时 `len(merged_chunks) == 0` 但 `len(entities_context) > 0`，系统 SHALL 输出 WARNING 级别日志标记 `[CHUNK_DEGRADED]`，包含实体数、关系数及建议排查方向。

#### Scenario: 有实体无 chunk 的降级告警
- **WHEN** 构建最终上下文，entities=34, relations=45, chunks=0
- **THEN** 日志输出 `[CHUNK_DEGRADED] chunks=0 but entities=34 relations=45. LLM answer quality may be degraded.`
- **THEN** 日志建议检查 `text_chunks_db.get_by_ids()` 返回值和 entity `source_id` 中的 chunk ID 格式

#### Scenario: 正常路径不告警
- **WHEN** chunks > 0 或 entities == 0
- **THEN** 不输出 `[CHUNK_DEGRADED]` 日志

### Requirement: RAG-Anything 端降级提示注入

当 RAG-Anything 的查询管线检测到检索上下文中 chunks=0 且 entities > 0 时，系统 SHALL 在传给 LLM 的 prompt 末尾追加降级提示，告知 LLM 当前只有实体名和关系路径可用。

#### Scenario: 降级提示注入到 LLM prompt
- **WHEN** `query.py` 的 RRF 或 graph 模式构建 prompt 前检测到 `context` 中 chunk 相关部分为空
- **THEN** 在 `citation_instruction` 后追加：
  > ⚠️ 本次检索未能获取到关联的文本内容（chunks=0），以下回答仅基于实体名称和关系路径，可能不够详细。请优先引用实体关系信息，并明确告知用户哪些信息来自实体名而非原文。
- **THEN** 该提示仅当 chunks=0 时追加

#### Scenario: 有 chunk 时不追加提示
- **WHEN** 上下文中有至少 1 个 chunk
- **THEN** 不追加降级提示
- **THEN** LLM prompt 与现有行为一致
