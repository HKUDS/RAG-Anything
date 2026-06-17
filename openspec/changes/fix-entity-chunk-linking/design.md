## Context

文档处理管线（`processor.py`）存在两条独立路径：
1. **文本路径**: 文本内容 → `lightrag.ainsert()` → 实体抽取 + chunk 链接
2. **多模态路径**: 表格/图片 → `_process_multimodal_content_batch_type_aware()` → 描述生成 → 实体抽取 → 存储

两者之间唯一的桥梁是 LightRAG 的 `merge_nodes_and_edges()`，但该合并仅针对**同一实体名在多个 chunk 中被抽取**的情况。若"毕业设计答辩"仅在文本 chunk 中出现，其 `source_id` 不会包含表格 chunk ID，即使表格 chunk 的原始数据包含该实体的属性值。

本设计在两条管线完成后增加一个桥接步骤：扫描多模态 chunk 内容中出现的实体名称，补建链接。

## Goals / Non-Goals

**Goals:**
- 文本实体能通过图谱遍历到达包含其数据的所有多模态 chunk
- 图谱检索通道的 BFS 遍历能发现多模态 chunk，提升 RRF 中图谱通道排名
- 支持现有文档重新处理以建立新链接

**Non-Goals:**
- 不改动 LightRAG 核心的实体抽取和合并逻辑
- 不修改 `chunk_entity_relation_graph` 的数据结构
- 不增加新的外部依赖

## Decisions

### 决策 1: 在 `_store_multimodal_main_entities()` 和 `_batch_merge_lightrag_style_type_aware()` 之间执行桥接

**选择**: 在 `processor.py` 的 `_process_multimodal_content_batch_type_aware()` 函数中，`_store_multimodal_main_entities()` 之后、`_batch_merge_lightrag_style_type_aware()` 之前，插入一个新步骤 `_link_entities_to_multimodal_chunks()`。

**理由**: 
- `_store_multimodal_main_entities()` 已将多模态主实体写入 graph，此时 graph 中有完整实体列表
- `_batch_merge_lightrag_style_type_aware()` 会调用 LightRAG 的 `merge_nodes_and_edges()`，链接信息可在该合并中一并处理
- 在此窗口操作避免额外的一次 graph 写入

**替代方案**:
- 方案 B: 在 `merge_nodes_and_edges()` 内部处理 → 需要修改 LightRAG 核心库，不可取
- 方案 C: 仅在查询时处理（当前 `_aquery_rrf()` 方案）→ 仅解决标注问题，不提升图谱通道排名

### 决策 2: 子串匹配 + mentions 边

**选择**: 使用子串匹配检测多模态 chunk 中是否包含实体名称（`entity_name in chunk_content`），匹配成功后：
1. 将 chunk_id 追加到实体的 `source_id` 列表
2. 创建 `(entity, chunk_id)` mentions 边（weight=5.0）

**理由**: 实体名称是短字符串，子串匹配速度快（O(n*m)），无需引入 embedding 相似度比较。

### 决策 3: 仅匹配长度 ≥ 3 的实体名

**选择**: 过滤掉长度 < 3 字符的实体名（如 "AI"、"A"），避免误匹配导致大量噪音链接。

**理由**: 短实体名（1-2 字符）在 chunk 内容中误匹配概率极高（如英文缩写）。

## Risks / Trade-offs

- **[风险] 子串误匹配**: "答辩"可能匹配到"答辩委员会"等不同实体 → **缓解**: 结合 token 重叠度（jieba）进行精确匹配；仅匹配 ≥ 3 字符实体
- **[风险] 处理耗时增加**: 新增 O(实体数 × 多模态 chunk 数) 扫描 → **缓解**: 实体数通常在百级别，chunk 在十级别，总操作量 < 10000 次子串匹配，毫秒级
- **[权衡] 仅处理多模态 chunk 而非全部 chunk**: 文本 chunk 已有 `lightrag.ainsert()` 自动建立的链接，不需要重复处理

## Migration Plan

1. 新增 `_link_entities_to_multimodal_chunks()` 函数
2. 在 `_process_multimodal_content_batch_type_aware()` 中调用
3. 已有文档需 `force_reprocess=true` 重新处理
4. 无破坏性变更，无需数据迁移
