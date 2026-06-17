## Why

当前 RAG-Anything 的检索回答中，引用来源仅以简单的 `[Doc N]` 标记出现在回答文本中，既不包含被引用的原文内容，也无法点击跳转到源文档位置。用户无法快速验证回答的准确性——他们必须手动翻阅大量原始文档才能确认 AI 回答是否可靠。这在智能制造、教学等对准确性要求极高的场景下是不可接受的。虽然制造模块已实现 `SourceTracer` + `[来源 N]` 格式的引用追踪，但通用 RAG 流程完全没有结构化引用能力。现在是时候将引用能力系统化到整个查询管线中。

## What Changes

- **后端数据结构升级**：`ScoredChunk` 增加 `file_path`、`document_name`、`chunk_index` 等源追踪字段，使每个检索到的文本块都能追溯到源文档的具体位置
- **LLM 提示词增强**：在通用 RAG 查询提示中强制要求 LLM 使用 `[来源 N]` 格式标注引用，每条引用包含被引用的原文摘录
- **引用解析与结构化输出**：复用制造模块的 `CITATION_PATTERN` 解析逻辑，从 LLM 回答中提取结构化引用列表，随回答一起返回给前端
- **前端引用面板**：在 AgentChatPage 中新增引用来源展示区域，显示每条引用的原文摘录、源文档名称，支持点击跳转到原文位置
- **流式查询响应增强**：在 SSE `done` 事件中返回 `citations` 字段，确保流式和非流式查询均有完整引用信息

## Capabilities

### New Capabilities

- `citation-source-tracing`: 检索结果到源文档的追溯能力 —— `ScoredChunk` 携带文档路径、文档名、chunk 序号，查询管线在所有模式（RRF/Graph/LightRAG）下均填充这些字段
- `citation-structured-output`: LLM 回答中的结构化引用提取 —— 通用 RAG 提示强制 `[来源 N]` 标记格式，后端解析回答文本提取引用列表，每条引用包含来源编号、被引用原文摘录、源文档标识
- `citation-frontend-display`: 前端引用展示与跳转 —— 回答下方展示引用来源卡片/面板，显示原文摘录，源文档名称，点击可跳转/定位到原文位置

### Modified Capabilities

<!-- 本次变更不修改现有 spec 级别的行为要求，仅在此基础上新增引用能力 -->

## Impact

- **`raganything/hybrid_search.py`**: `ScoredChunk` 新增 `file_path`, `document_name`, `chunk_index` 字段
- **`raganything/query.py`**: 所有查询模式（`_aquery_rrf`, `_aquery_graph`, LightRAG 直调）需填充 chunk 源信息并增强 LLM 提示词
- **`raganything/prompt.py`**: 新增引用格式提示模板
- **`server.py`**: `/api/query` 和 `/api/query/stream` 响应中新增 `citations` 字段
- **`raganything/processor.py`**: chunk 数据管线中传递源文档信息
- **`frontend/src/pages/AgentChatPage.jsx`**: 新增引用来源展示组件，自定义 Markdown 渲染器处理引用链接点击
- **`raganything/manufacturing/agent/source_tracer.py`**: 通用化 `extract_citations()` 逻辑，供通用 RAG 管线复用
