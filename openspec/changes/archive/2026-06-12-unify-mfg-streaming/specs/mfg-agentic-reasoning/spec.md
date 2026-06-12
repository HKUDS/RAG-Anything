# Manufacturing Agentic Reasoning (Delta)

## MODIFIED Requirements

### Requirement: 推理轨迹输出
AgentResponse SHALL 包含 `trace` 字段记录推理轨迹。流式模式下，非 FINISH 步骤的 thinking 事件 SHALL 在推理过程中实时产出（非事后重放），FINISH 步的 token SHALL 为 LLM 真流式输出。

#### Scenario: 流式输出推理过程
- **WHEN** 用户通过 `/api/manufacturing/qa/stream` 发起流式问答
- **THEN** 系统 SHALL 在 ReAct 循环每步完成后即时发送 `{"type":"thinking","step":N,"thought":"...","action":"..."}` 事件，在 FINISH 步逐 token 发送 `{"type":"token","content":"..."}` 事件，流式体验与通用智能体一致
