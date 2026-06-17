## Why

当前内联原文引用在 RRF/Graph 模式下工作正常（有文档名），但 LightRAG 原生模式（hybrid/mix/local/global/naive）返回的是图谱实体数据而非文档 chunk——没有文档名，LLM 只能编造 `（来源实体："xxx"）`。用户要求所有检索模式都能正确显示 `"原文摘录..."（来源：文档名）` 格式。

## What Changes

- **LightRAG 原生模式上下文增强**：在 `server.py` 构建 prompt 时，从 LightRAG 返回的检索内容中提取 chunk 引用，通过 `chunk_source_cache` 注入文档名
- **后处理注入文档名**：解析 LightRAG 返回的 context 中的 chunk_id / entity 引用，批量查询源文档信息，在 context 头部追加文档列表，供 LLM 引用
- **统一来源格式**：所有模式输出统一为 `"原文..."（来源：文档名）`

## Capabilities

### Modified Capabilities

- `inline-source-quoting`: 从"仅部分模式生效"升级为"所有检索模式生效"

## Impact

- **`server.py`**: `final_prompt`（非流式+流式）中注入文档列表；从 LightRAG context 中解析 chunk 引用并查询源信息
- **`raganything/query.py`**: 无需改动（RRF/Graph 已有文档名）
- **`raganything/agentic_rag.py`**: 无需改动（提示已更新）
