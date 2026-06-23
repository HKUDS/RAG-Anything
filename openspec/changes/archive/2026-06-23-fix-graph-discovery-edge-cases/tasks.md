## 1. ScoredChunk 文档来源信息填充

- [x] 1.1 在 `GraphRetriever.search_with_paths()` 中，从 `text_chunks.get_by_id()` 返回的 chunk_data 提取 `document_name` 和 `file_path`，设置到 `ScoredChunk` 构造参数
- [x] 1.2 确保 `file_path` 使用 `_get_file_reference()` 一致性处理（与 entity 存储对齐）

## 2. 图谱发现重试机制

- [x] 2.1 在 `_discover_images_via_graph()` 中，当 `search_with_paths` 返回 0 个 matched 实体时，增加最多 2 次重试（间隔 1 秒）
- [x] 2.2 重试逻辑需包装在 try/except 内，确保单次重试失败不中断整体流程
- [x] 2.3 在所有重试均失败时记录 info 日志（区别于异常 warning），不影响下游 bigram 兜底

## 3. AgenticRAG bigram 回填文本收集对齐

- [x] 3.1 确认 AgenticRAG 路径 bigram 的 `scored_texts` 收集逻辑与 Normal RAG 路径完全一致（仅 score > 0 且 paths 非空时收集，且经过 `_existing_content_ids` 去重过滤）
- [x] 3.2 移除 AgenticRAG 路径 bigram 中冗余的变量名差异（如 `scored` → `scored_images`，与 Normal RAG 对齐）

## 4. 验证

- [x] 4.1 验证新上传文档触发查询时，`[IMG-GRAPH]` 日志中回填文本的文档来源不再显示"未知文档"
- [x] 4.2 验证图谱未就绪时的重试行为（`[IMG-GRAPH]` 日志中应出现 "重试" 或 matched=0 的信息）
- [x] 4.3 验证 AgenticRAG 路径 bigram 回填文本中不含 score=0 的冗余内容
