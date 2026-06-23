## Why

经过上一轮 `fix-image-recall-all-modes` 的代码审查，发现图谱图片发现功能存在 3 个边缘问题：图谱来源 chunk 的文档名永远为"未知文档"（`search_with_paths` 创建的 `ScoredChunk` 未设置 `document_name`/`file_path`）；文档上传后实体图谱尚未构建完成时查询会静默错过 `belongs_to` 边；AgenticRAG 路径 bigram 的 `scored_texts` 收集逻辑与 Normal RAG 路径不一致。这些问题不影响功能正确性但影响可观测性、鲁棒性和代码一致性。

## What Changes

- 在 `GraphRetriever.search_with_paths()` 中，为 `ScoredChunk` 填充 `document_name` 和 `file_path`，使图谱来源的回填文本能正确标注文档来源
- 为 `_discover_images_via_graph()` 增加重试机制：匹配实体数为 0 时最多重试 2 次（间隔 1s），以容忍图谱构建的异步延迟
- AgenticRAG 路径 bigram 的 `scored_texts` 收集逻辑与 Normal RAG 路径对齐（仅收集 score > 0 的 chunk，跳过 score=0 的无意义条目）

## Capabilities

### New Capabilities

<!-- No new capabilities — all changes are refinements to existing graph-image-discovery -->

### Modified Capabilities

- `graph-image-discovery`: 图谱来源 chunk 需携带文档来源信息；图谱发现需容忍异步构建延迟；bigram 回填文本收集逻辑需统一

## Impact

- 受影响文件：`raganything/graph_rag/__init__.py`（`search_with_paths` 增加 `document_name`/`file_path`）、`raganything/routers/agent.py`（重试逻辑、AgentiCRAG bigram 对齐）
- 无 API 变更、无数据库 schema 变更、无**BREAKING** 变更
- 无新增外部依赖
