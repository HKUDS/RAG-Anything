## 1. 提示词替换 — 内联原文引用指令

- [x] 1.1 在 `raganything/prompt.py` 中将 `CITATION_FORMAT_INSTRUCTION` 替换为 `INLINE_QUOTE_INSTRUCTION`（要求 LLM 用引号直接嵌入原文摘录，不使用 `[来源 N]` 标记）
- [x] 1.2 在 `raganything/query.py` 的 `_aquery_rrf()` 中将 `CITATION_FORMAT_INSTRUCTION` 引用替换为 `INLINE_QUOTE_INSTRUCTION`
- [x] 1.3 在 `raganything/query.py` 的 `_aquery_graph()` 中将 `CITATION_FORMAT_INSTRUCTION` 引用替换为 `INLINE_QUOTE_INSTRUCTION`
- [x] 1.4 在 `server.py` 非流式 `final_prompt` 中将 `[来源 N]` 格式要求替换为内联引用指令
- [x] 1.5 在 `server.py` 流式 `final_prompt` 中将 `[来源 N]` 格式要求替换为内联引用指令
- [x] 1.6 在 `raganything/agentic_rag.py` ReAct 系统提示中将规则 12 替换为内联引用规则
- [x] 1.7 在 `raganything/agentic_rag.py` CoT 系统提示中将规则 6 替换为内联引用规则

## 2. 移除引用解析和后端端点

- [x] 2.1 在 `server.py` 非流式端点中移除 `citations` 解析逻辑和响应中的 `citations` 字段
- [x] 2.2 在 `server.py` 流式端点 SSE `done` 事件中移除 `citations` 字段
- [x] 2.3 移除 `server.py` 中的 `/api/document/open` 端点
- [x] 2.4 移除 `server.py` 中的 `/api/document/context` 端点
- [x] 2.5 移除 `server.py` 中不再需要的 `citation_parser` 导入

## 3. 前端清理 — 移除引用 UI 组件

- [x] 3.1 在 `AgentChatPage.jsx` 中移除 `CitationPanel` 导入和渲染
- [x] 3.2 在 `AgentChatPage.jsx` 中移除 `CitationMarkdown` 组件，恢复为 `<ReactMarkdown components={markdownComponents}>{m.content}</ReactMarkdown>`
- [x] 3.3 在 `AgentChatPage.jsx` 中移除 `highlightedCitation` 状态和相关的 `onClick` 事件委托
- [x] 3.4 在 `AgentChatPage.jsx` SSE `done` 事件处理中移除 `citations` 字段
- [x] 3.5 删除 `frontend/src/components/CitationPanel.jsx`
- [x] 3.6 在 `frontend/src/utils/api.js` 中移除 `openDocument` 和 `getDocumentContext` 方法
- [x] 3.7 在 `frontend/src/index.css` 中移除 `.citation-marker` 样式

## 4. 验证

- [x] 4.1 验证 RRF/Graph 模式下 LLM 回答包含内联原文引用
- [x] 4.2 验证 LightRAG 原生模式下 LLM 回答包含内联原文引用
- [x] 4.3 验证 Agentic RAG 模式下 LLM 回答包含内联原文引用
- [x] 4.4 验证前端正常渲染（无 CitationPanel、无 citation-marker 样式）
- [x] 4.5 验证后端启动无报错
