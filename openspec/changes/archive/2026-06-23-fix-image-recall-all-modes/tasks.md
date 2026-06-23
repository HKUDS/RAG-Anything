## 1. Core Implementation — Graph Image Discovery Function

- [x] 1.1 在 `raganything/routers/agent.py` 中新增 `_discover_images_via_graph()` 异步函数，实现：实体匹配（复用 GraphRetriever）→ 邻居遍历找到 image 类型实体 → 从 source chunk 提取图片路径 → 构建回填文本
- [x] 1.2 实现去重逻辑：跳过 ctx 中已存在的 chunk（前 80 字符匹配），图片路径去重
- [x] 1.3 实现异常安全：HybridSearchEngine/GraphRetriever 不可用时返回空列表，不抛异常；所有异常 catch 后记录 warning 日志并返回空

## 2. Integration — Normal RAG Query Path

- [x] 2.1 在 `agent_query_stream()` 的普通 RAG 路径（agent_mode="none"）中，于 `extract_image_paths(ctx)` 和 bigram 兜底之间插入 `await _discover_images_via_graph()` 调用
- [x] 2.2 图谱发现返回非空结果时，将回填文本追加到 ctx，跳过 bigram 兜底
- [x] 2.3 图谱发现返回空时，继续执行现有 bigram 兜底逻辑（行为不变）

## 3. Integration — AgenticRAG Query Path

- [x] 3.1 在 `agent_query_stream()` 的 AgenticRAG 路径（agent_mode ∈ {"react", "cot"}）的图片提取块中，于现有 bigram 扫描之前插入 `await _discover_images_via_graph()` 调用
- [x] 3.2 确保发现的图片路径合并到 `agent_images` 变量，回填文本合并到 `all_retrieved_text`

## 4. Verification

- [x] 4.1 使用不同查询模式（rrf/graph/hybrid/naive/local/global/mix）对含图表的文档提问，验证每种模式都能返回相关图片
- [x] 4.2 验证 fallback 链：确认 `extract_image_paths(ctx)` 命中时不会触发图谱发现；图谱发现命中时不会触发 bigram
- [x] 4.3 验证 AgenticRAG 路径（react/cot）的图片召回同样生效
- [x] 4.4 验证无图片文档查询不产生额外开销（日志中无 `[IMG-GRAPH]` 条目）
