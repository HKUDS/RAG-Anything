# Two-Tier QA Strategy

## Purpose

制造 QA 引擎采用两级策略：简单问题直接检索+LLM 生成（~3s），复杂问题回退 AgenticRAG 多步推理（~10s）。

## Requirements

### Requirement: Tier 1 直接检索
QAEngine.answer() SHALL 先执行一次 RRF 检索获取上下文。若上下文 ≥ 200 字符，直接构造 prompt 调用 LLM 生成回答，不启动 AgenticRAG。

#### Scenario: 简单问题快速路径
- **WHEN** RRF 检索返回 ≥ 200 字符上下文
- **THEN** 系统 SHALL 跳过 AgenticRAG，用检索上下文直接生成回答，总耗时 < 5s

#### Scenario: 无检索结果直接 AgenticRAG
- **WHEN** RRF 检索返回 < 50 字符上下文
- **THEN** 系统 SHALL 跳过直接生成，立即启动 AgenticRAG 多步推理

#### Scenario: 低置信度回退
- **WHEN** 直接生成后置信度 < 0.3
- **THEN** 系统 SHALL 回退 AgenticRAG 重新推理

### Requirement: Tier 1 流式路径
QAEngine.answer_stream() SHALL 在 Tier 1 直接检索路径中，以 LLM stream=True 逐 token 输出，yield 1 条 thinking + N 条 token + done。

#### Scenario: 流式快速路径
- **WHEN** RRF 检索上下文充分（≥ 200 字符）
- **THEN** answer_stream SHALL yield: thinking(1条) → token(N条) → done(1条)，首 token < 5s
