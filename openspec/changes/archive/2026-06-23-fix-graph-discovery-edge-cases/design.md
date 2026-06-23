## Context

`fix-image-recall-all-modes` 已实现基于实体图谱的图片发现 (`_discover_images_via_graph`)，但 Code Review 发现 3 个边缘缺陷：

1. `GraphRetriever.search_with_paths()` 构造 `ScoredChunk` 时未填充 `document_name`/`file_path`，导致回填文本的文档来源永远是"未知文档"
2. 文档上传后图谱异步构建，查询可能在 `belongs_to` 边建立前执行，此时 `_match_entities` 返回 0 个实体，图谱发现静默失败
3. AgenticRAG 路径 bigram 的 `scored_texts` 收集逻辑（已修复的版本）与 Normal RAG 路径存在冗余计算和格式不一致

## Goals / Non-Goals

**Goals:**
- 图谱发现的回填文本正确标注文档来源
- 容忍图谱异步构建的时序延迟（最多 3 次尝试）
- AgenticRAG 与 Normal RAG 路径的 bigram 回填逻辑完全一致
- 最小改动，不引入新依赖

**Non-Goals:**
- 不改变 Bigram 的核心匹配算法
- 不强约束图谱构建时序（这是 LightRAG 的职责）
- 不修改数据持久化层

## Decisions

### 决策 1：在 `search_with_paths()` 中填充 Source 字段

**选择**：在现有 `text_chunks.get_by_id()` 调用后，从 chunk_data 提取 `document_name` 和 `file_path` 并设置到 `ScoredChunk`
**备选**：在 `_discover_images_via_graph` 中二次查询 chunk 元数据

**理由**：
- `search_with_paths` 内部已经调用 `text_chunks.get_by_id()` 获取 content，chunk_data 中包含这些字段
- 避免额外的数据库查询
- 一次修改惠及所有使用 `ScoredChunk` 的地方

### 决策 2：重试机制在 `_discover_images_via_graph` 内实现

**选择**：在 matched 实体数为 0 时，最多重试 2 次，间隔 1 秒
**备选**：在 LightRAG pipeline 中增加同步等待点；或使用 callback 通知图谱就绪

**理由**：
- 重试是侵入性最小的方案，不修改 LightRAG 内部逻辑
- 实体提取通常在 2-3 秒内完成，2 次 1s 重试覆盖大部分场景
- Total added latency ≤ 2s（仅在 matched=0 时触发），符合 agent 流式响应的延迟预算
- 不引入复杂的同步原语或跨进程通知

### 决策 3：AgenticRAG bigram 直接复刻 Normal RAG 的收集逻辑

**选择**：AgenticRAG 的 bigram 遍历中，仅在 score > 0 且 paths 非空时收集 `scored_texts`
**备选**：提取共享函数统一两个路径

**理由**：
- `scored_texts` 的唯一消费者是 `_build_backfill_context`，它按 score 降序排列；score=0 的条目天然排在末尾且无实用价值
- 直接对齐逻辑减少差异，降低未来维护成本
- 不提函数级别的抽象——两个路径的 bigram 虽相似但仍有差异（ctx 变量、日志格式），过早抽象得不偿失

## Risks / Trade-offs

- **[风险] 重试增加延迟** → 仅在 matched=0 时重试，常规命中路径无额外延迟；最坏 +2s 在 streaming 场景仍可接受
- **[风险] `document_name` 在某些存储中可能为空** → `_discover_images_via_graph` 已有三级 fallback：`document_name` → `file_path` → "未知文档"
- **[取舍] 重试是启发式的** → 不保证重试后一定能匹配；如果图谱构建耗时超过 2s 仍会 fallback 到 bigram，但这是 acceptable degradation

## Migration Plan

1. 部署：修改 `search_with_paths()` 和 `agent.py`，无配置变更，无数据迁移
2. 回滚：revert 代码即可
3. 验证：上传新文档后立即查询 → 确认重试日志出现 + 文档名正确显示
