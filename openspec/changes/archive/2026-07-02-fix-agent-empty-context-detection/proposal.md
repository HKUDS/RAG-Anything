## Why

当知识库检索无结果时，LightRAG 的 `aquery(only_need_context=True)` 返回 `PROMPTS["fail_response"]`（`"Sorry, I'm not able to provide an answer to that question.[no-context]"`）而非空字符串或 `None`。`agent_query_stream` 中检测"是否有有效文本块"的逻辑仅依赖 `"[来源 " in ctx` 启发式判断，未能识别 fail_response，导致将无效的 fail_response 字符串作为"上下文"传给 LLM，同时附加误导性的"降级提示"。用户看到的是 LLM 基于 fail_response 文本产生的无意义回答，而非"知识库暂无相关数据"的明确反馈。

## What Changes

- 在 `agent_query_stream` 普通 RAG 路径（agent_mode=none）中，增加对 LightRAG fail_response 的检测（`"[no-context]" in ctx`）
- 当检测到 fail_response 时，向用户反馈"知识库中暂无相关数据"，自动降级为 bypass 模式（让 LLM 用自身知识回答并注明）
- 修复 `_has_chunks` 检测逻辑，使其覆盖 fail_response 和上下文过短的情况
- 同步修复 AgenticRAG 路径（ReAct/CoT）中相同的空上下文检测盲区（CoT 路径已有 try-except 兜底但无明确检测）

## Capabilities

### New Capabilities

- `agent-empty-context-handling`: 智能体查询流中空检索上下文的检测与降级处理——当 LightRAG 返回 fail_response 或上下文无实质文本块时，不再将其作为有效上下文传给 LLM，改为明确告知用户并降级到 bypass 模式

### Modified Capabilities

<!-- No existing specs are modified by this change -->

## Impact

- **Affected code**: `raganything/routers/agent.py` (line ~534, ~588-590, ~396-400 for CoT path)
- **Affected API**: `POST /api/agents/{agent_id}/query/stream` — 行为变更：空检索结果时返回明确的"无数据"提示 + 降级回答
- **Dependencies**: 依赖 LightRAG `PROMPTS["fail_response"]` 中的 `"[no-context]"` 标记（LightRAG 内部约定，非公开 API）
