## Why

当前 `ANSWER_FORMAT_INSTRUCTION` 允许 LLM 在检索内容无文档名时省略文档来源，且 `【引用来源】` 块的文档名要求不是强制性。用户需要**每条引用都明确标注来自哪篇文档**，确保回答可追溯。

## What Changes

- **强化 prompt 指令**：将"若有文档名则使用文档名"改为"每条引用必须标注所属文档名"，文档名缺失时明确说明
- **增强检索上下文**：确保检索到的每个 chunk 在上下文中都带有清晰的文档名标签，让 LLM 能正确映射来源编号到文档名
- **【引用来源】块强制文档名**：每个 `[来源 N]` 条目必须包含文档名，不可省略

## Capabilities

### Modified Capabilities

- `citation-structured-output`: 引用格式指令中"文档名"要求从"可选"升级为"强制"；每个 `[来源 N]` 标记对应的引用条目必须包含文档名

## Impact

- **受影响代码**: `raganything/prompt.py`（`ANSWER_FORMAT_INSTRUCTION` 第3、4条）、`server.py`（`_get_kb_doc_list` 返回格式）、`server.py`（`query_rag` 和 `query_rag_stream` 的 `final_prompt` 中 doc_list 注入方式）
- **不影响**: 前端引用面板（已有 `citation-frontend-display` 处理）
