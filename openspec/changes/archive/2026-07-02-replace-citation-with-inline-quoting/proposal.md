## Why

当前的 `[来源 N]` 标记 + `【引用来源】` 块 + CitationPanel 引用系统过于复杂：用户需要点击上标、展开面板、查看摘录才能验证原文——流程断裂、体验割裂。用户真正需要的是：**在回答中直接看到被引用的原文内容**，一目了然，无需任何额外操作。这个需求在所有检索模式下都应该生效。

## What Changes

- **移除引用标记系统**：去掉 LLM 提示中的 `[来源 N]` 格式指令和 `【引用来源】` 块要求
- **移除前端引用面板**：去掉 CitationPanel 组件及相关集成代码
- **移除引用解析器**：去掉 `citation_parser.py` 模块（或保留但不再强制使用）
- **新增内联原文引用指令**：在所有检索模式的 LLM 提示中，要求 LLM 在引用检索内容时直接嵌入原文摘录，用引号标注
- **全模式覆盖**：RRF、Graph、LightRAG 原生（hybrid/mix/local/global/naive）、Agentic RAG（ReAct/CoT）全部生效

## Capabilities

### New Capabilities

- `inline-source-quoting`: LLM 在回答中直接嵌入检索内容的原文摘录，以引号标注，使读者无需额外操作即可验证信息准确性

### Modified Capabilities

- `citation-source-tracing`: 保留 ScoredChunk 的源追溯字段（file_path/document_name/chunk_index）作为上下文增强，但不再用于结构化引用输出
- `citation-structured-output`: 移除 `[来源 N]` 格式要求，改为内联引用的自然语言指令
- `citation-frontend-display`: 移除 CitationPanel 组件，回答恢复为纯 Markdown 渲染

## Impact

- **`raganything/prompt.py`**: 替换 `CITATION_FORMAT_INSTRUCTION` 为 `INLINE_QUOTE_INSTRUCTION`
- **`raganything/query.py`**: RRF/Graph 模式提示切换为新指令
- **`raganything/agentic_rag.py`**: ReAct/CoT 系统提示切换为内联引用规则
- **`server.py`**: 非流式/流式提示切换；移除 `/api/query` 中的 `citations` 解析；移除 `/api/document/open` 和 `/api/document/context` 端点
- **`frontend/src/pages/AgentChatPage.jsx`**: 移除 CitationPanel 集成、CitationMarkdown 组件、citation 事件处理
- **`frontend/src/components/CitationPanel.jsx`**: 删除
- **`raganything/citation_parser.py`**: 保留模块（制造模块仍依赖）但通用 RAG 不再调用
- **`raganything/hybrid_search.py`**: ScoredChunk 源追溯字段保留（用于上下文增强）
- **`raganything/processor.py`**: chunk source cache 保留
