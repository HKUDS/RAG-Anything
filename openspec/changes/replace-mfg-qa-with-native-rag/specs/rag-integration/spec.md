# RAG Integration (Delta)

## MODIFIED Requirements

### Requirement: QA 引擎对接 RAG 检索
制造智能体 QA 端点 SHALL 直接调用 LightRAG 原生 `aquery(mode="hybrid")` 进行检索增强生成，而非通过自定义 QAEngine + RRF 管线。

#### Scenario: 检索增强回答
- **WHEN** 用户通过 `/api/manufacturing/qa` 发起文本问答
- **THEN** 系统 SHALL 调用 `LightRAG.aquery(query, mode="hybrid", system_prompt="你是智能制造教学专家...")` 并返回结果

#### Scenario: 流式回答
- **WHEN** 用户通过 `/api/manufacturing/qa/stream` 发起流式问答
- **THEN** 系统 SHALL 先调用 `LightRAG.aquery(only_need_context=True)` 获取上下文，再用 `llm_model_func(stream=True)` 逐 token 输出

## REMOVED Requirements

### Requirement: QA 引擎对接 RAG 检索
**Reason**: 原要求使用自定义 HybridSearchEngine 三路融合检索。该管线存在 4 个已验证 bug，检索召回率低于 LightRAG 原生查询，且不提供差异化价值。
**Migration**: QA 端点直接调用 `LightRAG.aquery(mode="hybrid")`，与普通智能体共享同一检索代码路径。
