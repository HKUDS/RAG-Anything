## Why

制造智能体当前流式输出是"伪流式"——AgenticRAG 完整执行完 ReAct 推理后，才将 answer 按 50 字符分块发送。通用智能体的流式是真正的 token-by-token LLM 输出。两者体验不一致：制造 QA 用户需要等待推理完全结束才能看到回答的第一行文字，而通用 QA 用户边看边等。

## What Changes

- **AgenticRAG 改造**：ReAct 循环在检测到 `Action: FINISH` 时，不再等待完整 LLM 响应后返回，而是将 LLM 的 stream generator 暴露给调用方，由调用方逐 token 消费
- **QAEngine 新增 `answer_stream()`**：返回 async generator，yield `thinking` 事件（非 FINISH 步的 trace）和 `token` 事件（FINISH 步的 LLM token）
- **`/api/manufacturing/qa/stream`**：使用 `answer_stream()` 替代当前的分块重放，SSE 格式与通用智能体完全一致
- **前端**：制造 QA 的 token 事件处理逻辑与通用智能体统一，移除 50 字符分块的 hack

## Capabilities

### New Capabilities
- `mfg-true-streaming`: AgenticRAG FINISH 步骤的真流式 token 输出 + QAEngine.stream_answer() async generator

### Modified Capabilities
- `mfg-agentic-reasoning`: 流式输出场景从"推理完成后分块重放 trace+answer"改为"非 FINISH 步实时输出 thinking，FINISH 步真流式输出 token"

## Impact

- `raganything/agentic_rag.py` — 新增 `run_stream()` 方法，对 FINISH 步返回 LLM stream generator
- `raganything/manufacturing/agent/qa_engine.py` — 新增 `answer_stream()` async generator
- `server.py:2783` — `/api/manufacturing/qa/stream` 使用 `answer_stream()`
- `frontend/src/pages/ManufacturingAgentPage.jsx` — token 事件处理改为逐字追加（移除 50 字符感知）
