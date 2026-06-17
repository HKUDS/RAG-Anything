## 1. 数据结构升级 — ScoredChunk 源追溯

- [x] 1.1 `ScoredChunk` 新增 `file_path`、`document_name`、`chunk_index` 可选字段（默认值 `None`），在 `raganything/hybrid_search.py` 中修改 dataclass 定义
- [x] 1.2 在 `raganything/processor.py` 中新增 `get_doc_source_info(chunk_id)` 方法，通过 chunk_id 查询 doc_status 返回源文档信息（`file_path`, `document_name`）
- [x] 1.3 在 `get_doc_source_info` 基础上新增 `batch_get_doc_source_info(chunk_ids)` 批量查询方法，减少多次查询开销

## 2. 引用解析模块 — citation_parser.py

- [x] 2.1 创建 `raganything/citation_parser.py`，实现 `extract_citations(text: str) -> list[dict]`，支持解析 `[来源 N]` 标记和原文摘录（`| 原文："..."` 部分）
- [x] 2.2 实现 `parse_citation_block(text: str) -> dict` 解析 `【引用来源】` 块中的每条引用条目，提取 `index`、`document_name`、`excerpt`
- [x] 2.3 实现 `has_citations(text: str) -> bool` 检测方法，判断回答是否包含引用标记
- [x] 2.4 将 `raganything/manufacturing/agent/source_tracer.py` 改为导入 `citation_parser.extract_citations`，移除内联的正则逻辑

## 3. 查询管线改造 — query.py 提示词与源信息

- [x] 3.1 在 `raganything/prompt.py` 中新增 `CITATION_FORMAT_INSTRUCTION` 常量，定义 `[来源 N]` 格式指令模板
- [x] 3.2 在 `raganything/query.py` 的 `_aquery_rrf()` 中：构建 context 时为每个 chunk 填充 `file_path`、`document_name`、`chunk_index`；将 `CITATION_FORMAT_INSTRUCTION` 注入 LLM 提示
- [x] 3.3 在 `_aquery_graph()` 中同样填充源信息并注入引用格式指令
- [x] 3.4 在 LightRAG 原生模式查询包装层中填充源信息并注入引用格式指令
- [x] 3.5 在 `raganything/agentic_rag.py` 的 ReAct 系统提示中追加引用格式要求（FINISH 动作输出 `[来源 N]` 标记和【引用来源】块）

## 4. 服务端响应增强 — server.py

- [x] 4.1 在 `/api/query` 非流式端点中：解析 LLM 回答中的引用标记，构建 `citations` 列表，加入响应 JSON
- [x] 4.2 在 `/api/query/stream` 流式端点中：在 SSE `done` 事件中返回 `citations` 字段
- [x] 4.3 新增 `/api/document/open` 端点，接收 `file_path` 参数，通过 `os.startfile()`/`open`/`xdg-open` 打开文件
- [x] 4.4 新增 `/api/document/context` 端点，接收 `file_path` + `chunk_index` 参数，返回该 chunk 周围的上下文文段

## 5. 前端引用展示 — CitationPanel 组件

- [x] 5.1 创建 `frontend/src/components/CitationPanel.jsx` 组件：可折叠面板，展示引用来源列表（源文档名 + 原文摘录），支持展开/折叠切换，限制最多展示 10 条
- [x] 5.2 在 `frontend/src/pages/AgentChatPage.jsx` 中集成 `CitationPanel`：在每条 AI 消息气泡下方渲染，传入 `citations` 数据
- [x] 5.3 自定义 `ReactMarkdown` 组件：将 `[来源 N]` 正则匹配并渲染为可点击上标元素（`<sup>` 样式），点击触发展开引用面板 + 高亮对应条目
- [x] 5.4 实现源文档跳转交互：点击源文档名调用 `/api/document/open`，添加加载状态和失败提示（"文件已移动或删除"）
- [x] 5.5 实现"查看上下文"功能：点击引用条目展开 chunk 上下文预览，调用 `/api/document/context` 加载，高亮匹配文本
- [x] 5.6 在 `frontend/src/utils/api.js` 中新增 `openDocument(filePath)` 和 `getDocumentContext(filePath, chunkIndex)` API 方法

## 6. 质量保障与测试

- [x] 6.1 验证所有现有查询模式的向后兼容性（RRF/Graph/LightRAG 模式在无 citations 客户端时正常工作）
- [x] 6.2 验证 `[来源 N]` 格式指令在不同 LLM 模型下的遵循率
- [x] 6.3 验证前端 Markdown 渲染在引用标记存在时不影响正常格式化
- [x] 6.4 验证文件打开功能在不同操作系统（Windows/macOS/Linux）下的正确行为
