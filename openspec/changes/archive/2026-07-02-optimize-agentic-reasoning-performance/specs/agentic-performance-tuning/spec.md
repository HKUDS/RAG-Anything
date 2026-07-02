# Agentic Performance Tuning

## Purpose

优化 AgenticRAG 推理引擎的延迟，将 ReAct 单步推理从 ~50s 降到 < 10s，CoT 从 ~22s 降到 < 8s，通过分步 token 预算控制和轻量检索模式实现。

## ADDED Requirements

### Requirement: 分步 token 预算控制
`_call_llm_with_retry()` SHALL 接受 `is_final_step: bool` 参数。非 FINISH 步（is_final_step=False）SHALL 使用 `max_tokens=1024`，FINISH 步和 CoT 模式 SHALL 使用 `max_tokens=4096`/`2048`。

#### Scenario: 非 FINISH 步使用小 token 预算
- **WHEN** ReAct 循环中 LLM 需要产出 Thought + Action + Action Input JSON
- **THEN** max_tokens SHALL 为 1024（足以为 ~200 tokens 的实际需求留 5x 余量）

#### Scenario: FINISH 步使用大 token 预算
- **WHEN** Agent 决定 FINISH，需要产出完整最终回答
- **THEN** max_tokens SHALL 为 4096

### Requirement: SearchTool 轻量检索模式
SearchTool 在 AgenticRAG 上下文中 SHALL 使用 `mode="rrf"` 作为默认检索模式，top_k=30，max_total_tokens=8000。

#### Scenario: RRF 模式快速检索
- **WHEN** AgenticRAG 的 SearchTool 执行检索
- **THEN** SHALL 调用 `rag.aquery(query, mode="rrf", top_k=30, max_total_tokens=8000)`

#### Scenario: 可覆盖检索模式
- **WHEN** AgenticRAG 初始化时传入 `agent_query_mode="hybrid"`
- **THEN** SearchTool SHALL 使用指定模式而非默认 "rrf"

### Requirement: 无阻塞重试
LLM 调用重试 SHALL 不包含 `asyncio.sleep(1)`，直接重试。单次调用失败后立即发起第二次尝试。

#### Scenario: 快速重试
- **WHEN** LLM 第一次调用失败（返回空或异常）
- **THEN** 系统 SHALL 立即重试，不等待 1 秒

### Requirement: 流式路径共享优化逻辑
`run_stream()` 和 `_react_loop()` SHALL 共享相同的 token 预算和重试优化，通过统一调用 `_call_llm_with_retry()` 实现。

#### Scenario: run_stream 受益于优化
- **WHEN** 通过 run_stream() 执行 ReAct 推理
- **THEN** 每一步 LLM 调用 SHALL 使用分步 token 预算和无阻塞重试
