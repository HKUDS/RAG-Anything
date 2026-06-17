## Why

Hybrid 查询中，LightRAG 的 `_merge_all_chunks` 函数从实体 `source_id` 和关系 edges 中提取 chunk ID，然后通过 `text_chunks_db.get_by_ids()` 取回 chunk 数据。但在当前部署中，所有 chunk ID 解析后 `get_by_ids()` 均返回 `None`，导致 `merged_chunks` 为空（`origin_len=0`），最终传递给 LLM 的上下文中有 34 个实体 + 45 条关系路​​径但 **0 条 chunk 文本**。LLM 只能基于实体名和关系类型生成回答，无法引用原文，导致 `[来源 文档名]` 格式失效（因为根本没有 chunk 来生成来源标记）。

当前日志证据：
```
INFO: Raw search results: 61 entities, 60 relations, 0 vector chunks
INFO: Selecting 31 from 31 entity-related chunks by vector similarity
INFO: Find 16 additional chunks in 16 relations (deduplicated 0)
INFO: Selecting 16 from 16 relation-related chunks by vector similarity
INFO: Round-robin merged chunks: 0 -> 0 (deduplicated 0)
INFO: Final context: 34 entities, 45 relations, 0 chunks
```

## What Changes

- **新增** chunk ID 解析失败时的诊断日志，定位 `source_id` 中的 chunk ID 与实际 KV 存储 key 的不匹配点
- **新增** 当 `get_by_ids()` 全部返回 `None` 时的降级策略：尝试直接以 chunk ID 为 key 的 fallback 读取
- **新增** `source_id` 解析后 chunk ID 验证步骤，过滤掉不存在于 text_chunks_db 中的无效 ID
- **修改** `_find_related_text_unit_from_entities` / `_find_related_text_unit_from_relations` 返回值中添加 chunk 命中率统计，便于监控
- **修改** RAG-Anything 查询端（query.py、server.py）在接收到 `chunks=0` 上下文时展示降级提示，引导用户了解回答质量降低的原因

## Capabilities

### New Capabilities

- `chunk-resolution-fallback`: 当 entity/relation 引用的 chunk ID 无法在 text_chunks_db 中找到时，提供降级路径确保 LLM 仍能获得部分文本上下文
- `chunk-diagnostics-logging`: 对 chunk 解析过程添加结构化诊断日志，快速定位 chunk ID → 实际数据之间的断裂点

### Modified Capabilities

- `graph-channel-retrieval`: 修改图检索中关联 chunk 的获取逻辑，增加 chunk ID 有效性验证和 fallback
- `rrf-hybrid-search`: 修改 RRF 混合搜索中 chunk 合并阶段的结果验证，当 chunks=0 时触发降级

## Impact

- **Affected code**: `lightrag/operate.py`（`_find_related_text_unit_from_entities`、`_find_related_text_unit_from_relations`、`_merge_all_chunks`、`_build_context_str`）
- **Affected code**: `raganything/query.py`（RRF 和 graph 模式中的上下文构建）
- **Affected code**: `server.py`（chunks=0 时的降级展示）
- **No API changes**, **No breaking changes**
- **Risk**: 低。所有改动为防御性编程和诊断增强，不影响正常路径
