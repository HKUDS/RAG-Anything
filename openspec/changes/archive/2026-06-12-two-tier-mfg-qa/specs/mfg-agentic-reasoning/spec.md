# Manufacturing Agentic Reasoning (Delta)

## MODIFIED Requirements

### Requirement: QA 引擎使用 AgenticRAG 多步推理
QAEngine SHALL 在检索上下文不充分（< 50 字符或置信度 < 0.3）时回退到 AgenticRAG 多步推理，而非无条件走 ReAct 循环。

#### Scenario: 仅低质量检索触发 AgenticRAG
- **WHEN** 直接 RRF 检索返回 < 50 字符或置信度 < 0.3
- **THEN** QAEngine SHALL 启动 AgenticRAG 多步推理作为兜底

#### Scenario: 充分检索跳过 AgenticRAG
- **WHEN** 直接 RRF 检索返回 ≥ 200 字符充分上下文
- **THEN** QAEngine SHALL 不启动 AgenticRAG，直接构造 prompt 生成回答
