## Context

RAG-Anything 使用 LightRAG 的 hybrid search 管线构建查询上下文。该管线的 chunk 合并流程为：

1. `_merge_all_chunks()` 调用 `_find_related_text_unit_from_entities()` 从实体 `source_id` 提取 chunk ID 列表
2. 调用 `_find_related_text_unit_from_relations()` 从关系 edges 提取 chunk ID
3. 两次调用分别通过 `text_chunks_db.get_by_ids(chunk_ids)` 取回 chunk 数据
4. Round-robin 合并后传给 `_build_context_str()` 构建最终上下文

**当前故障**：步骤 3 中，`get_by_ids()` 对从 entity `source_id` 解析出的所有 chunk ID 返回 `None`（共 31+16=47 个 chunk ID 全部解析失败），导致步骤 4 中 `merged_chunks=[]`。

**约束**：
- LightRAG 是 pip 安装的第三方库，直接修改会丢失
- entity 的 `source_id` 字段格式由 LightRAG 内部决定（使用 `GRAPH_FIELD_SEP` 分隔符拼合多个 chunk ID）
- `text_chunks_db` 的 key 格式由 LightRAG 的 `compute_mdhash_id` 决定

## Goals / Non-Goals

**Goals:**
- 在 chunk 解析全部失败时，提供降级路径确保 LLM 获得部分文本上下文
- 添加诊断能力，快速定位 chunk ID 与实际存储 key 之间的不匹配
- 对现有正常路径零影响

**Non-Goals:**
- 不修改 LightRAG 的 chunk ID 生成策略（上游问题）
- 不改变 entity `source_id` 的存储格式
- 不引入新的外部依赖

## Decisions

### Decision 1: 防御层放在 LightRAG operate.py 的 patch 中

**选择**：在 `raganything/` 中维护一个对 `lightrag.operate` 的轻量 monkey-patch，在 `_find_related_text_unit_from_entities` 和 `_find_related_text_unit_from_relations` 的 `get_by_ids` 返回全空时，尝试 fallback 读取。

**替代方案**：
- 在 RAG-Anything 的 query.py 中检测 chunks=0 后重试：代码侵入性大，且需要重复整个查询管线，延迟翻倍
- 直接修 LightRAG 源文件：pip update 后丢失，不可维护

**为什么选 monkey-patch**：patch 文件独立，升级 LightRAG 时只需验证 patch 兼容性，不修改上游源码。

### Decision 2: Fallback 策略 — 直接 key 查询

当 `get_by_ids(chunk_ids)` 全部返回 None 时，遍历 chunk_ids 逐个调用 `text_chunks_db.get_by_id(chunk_id)`（非批量接口），记录哪些成功、哪些失败，并将成功取回的数据构建 result_chunks。

**为什么**：`get_by_id` 和 `get_by_ids` 可能使用不同的内部查找路径。即使批量接口失败，单条接口可能使用更简单的 key 查找。

### Decision 3: chunk ID 格式诊断

在 `_find_related_text_unit_from_entities` 中增加结构化日志：

```python
logger.info(
    f"Chunk resolution: {len(selected_chunk_ids)} IDs selected, "
    f"{success_count} resolved, {fail_count} not found in text_chunks_db"
)
if fail_count > 0:
    sample_ids = failed_ids[:3]  # Log up to 3 sample failed IDs
    logger.warning(
        f"Failed chunk IDs sample: {sample_ids}. "
        f"Verify that entity source_id chunk IDs match text_chunks_db keys."
    )
```

### Decision 4: RAG-Anything 端降级展示

在 `query.py` 和 `server.py` 的上下文构建完成后，检测 `chunks=0` 且 `entities > 0` 的情况：

- 在传给 LLM 的 prompt 中追加提示：
  > ⚠️ 本次检索未能获取到关联的文本内容（chunks=0），以下回答仅基于实体名称和关系路径，可能不够详细。
- 在 server.py 的日志中输出 `[CHUNK_DEGRADED]` 标记，便于运维监控

## Risks / Trade-offs

- **[R1] monkey-patch 可能与 LightRAG 未来版本不兼容** → 将 patch 版本检测放在 import 时，不匹配时跳过 patch 并发出警告
- **[R2] fallback 单条查询增加延迟** → 仅当批量接口全量失败时才触发，正常路径不受影响
- **[R3] 诊断日志可能在频繁查询时刷屏** → 使用 sampling（仅 log 前 3 个失败的 chunk ID），并在 60 秒内去重

## Open Questions

1. entity `source_id` 中存储的 chunk ID 是否与 `text_chunks_db` 实际 key 使用了不同的 hash 算法？（需查看 LightRAG 中 `compute_mdhash_id` 的输入和 `source_id` 的构建逻辑）
2. 是否在某些文档处理路径中（如 `insert_content_list`），chunk 在 `text_chunks_db` 中存储的 key 与 entity `source_id` 引用的 ID 存在格式差异？
