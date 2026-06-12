# RAG Integration (Delta)

## MODIFIED Requirements

### Requirement: QA 引擎对接 RAG 检索
制造智能体 QA 端点 SHALL 通过 AgenticRAG 的 SearchTool 间接调用 RAG 检索引擎，而非直接调用 `LightRAG.aquery()` 或自定义 HybridSearchEngine。SearchTool 封装检索逻辑，Agent 在推理循环中自主决定何时检索、检索什么。

#### Scenario: Agent 自主检索决策
- **WHEN** 用户通过 `/api/manufacturing/qa` 发起文本问答
- **THEN** AgenticRAG SHALL 在 ReAct 循环中自主判断是否需要检索、检索几次，通过 SearchTool 调用 `rag.aquery(mode="rrf", only_need_context=True)` 获取上下文

#### Scenario: 流式回答
- **WHEN** 用户通过 `/api/manufacturing/qa/stream` 发起流式问答
- **THEN** 系统 SHALL 先通过 AgenticRAG 执行推理（含 SearchTool 检索），再通过 SSE 流式输出思考过程和最终回答

#### Scenario: 检索超时降级
- **WHEN** SearchTool 调用 RAG 检索耗时超过 `AGENT_TOOL_TIMEOUT` 秒（默认 30）
- **THEN** Agent SHALL 收到超时提示，可基于已有信息 FINISH 或尝试其他工具，不阻塞整个推理流程
