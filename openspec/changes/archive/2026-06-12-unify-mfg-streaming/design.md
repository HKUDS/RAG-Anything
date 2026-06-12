## Context

AgenticRAG 的 `_react_loop()` 每步调用 `_call_llm_with_retry()` 获取完整 LLM 响应，然后 `_parse_action()` 解析 Thought/Action/Action Input。在 FINISH 步骤，Action Input 中的 answer 才是真正给用户看的内容。目前整个 answer 是一次性返回的 `str`，无法流式输出。

核心矛盾：ReAct 循环需要在每步**完整解析** LLM 输出以决定下一步（继续检索还是 FINISH），但 FINISH 步的用户回答应当**流式**输出以减少感知延迟。

## Goals / Non-Goals

**Goals:**
- AgenticRAG FINISH 步骤以真流式（LLM token-by-token）输出 answer
- 非 FINISH 步骤保持完整解析（不变）
- 制造 QA 流式端点 SSE 格式与通用智能体一致：`thinking` → `token` → `done`
- 前端制造 QA 页面统一 token 处理逻辑

**Non-Goals:**
- 不改变 ReAct 推理逻辑本身（步数、工具、解析规则）
- 不让非 FINISH 步骤流式输出（那会破坏解析）
- 不修改故障诊断和代码解析模块

## Decisions

### Decision 1: 通过回调/消费模式暴露 stream，而非改造 `run()`

`run()` 保持同步返回 `AgentResult`（向后兼容）。新增 `run_stream()` 方法，返回 `AsyncIterator[StreamEvent]`：

```python
@dataclass
class StreamEvent:
    type: str  # "thinking" | "token" | "done"
    step: int | None = None
    thought: str | None = None
    action: str | None = None
    content: str | None = None  # token text or final answer
```

`run_stream()` 内部逻辑：
- 前 N-1 步：与 `run()` 完全相同（完整解析 Thought/Action/Observation）
- 检测到 `Action: FINISH` 时：不调用 `_call_llm_with_retry()` 等待完整响应，改为调用 `self.llm_func(stream=True)`，将 FINISH 步的流式 token 转发给调用方
- 流式 token 全部收集后，拼成完整 answer 用于后处理（图片匹配、引用溯源）

### Decision 2: QAEngine 新增 `answer_stream()` 方法

保持 `answer()` 不变（返回 `AgentResponse`）。新增 `answer_stream()` 返回 async generator：

```python
async def answer_stream(self, query: str) -> AsyncIterator[dict]:
    # 调用 agentic_rag.run_stream()
    # 对 thinking 事件：直接 yield
    # 对 token 事件：收集 + yield
    # 流结束后：执行图片匹配、引用溯源
    # 最后 yield "done" 事件含 images/citations/confidence
```

### Decision 3: SSE 格式对齐通用智能体

通用智能体 SSE 格式：`{"type":"token","content":"..."}` → `{"type":"done",...}`

制造 QA 新增 thinking 事件（通用智能体也有，只是一条"正在检索..."），格式对齐：
- `{"type":"thinking","step":N,"thought":"...","action":"search"}` — 每步推理
- `{"type":"token","content":"..."}` — 逐 token（与通用完全一致）
- `{"type":"done","id":"...","elapsed":...}` — 结束

## Risks / Trade-offs

- **[风险] LLM 在 FINISH 步的流式输出格式不稳定**: 如果 LLM 在流式输出中不遵守 ReAct 格式（如 Action: 后面没有 JSON），结束后的完整文本解析可能失败。
  → **缓解**: `_parse_action()` 已有 fallback 逻辑（无法解析 JSON 时默认 FINISH+全文）。流式 token 收集后用同一个 `_parse_action()` 解析。

- **[风险] 两次 LLM 调用（非流式用于解析 + 流式用于输出）降低效率**: 理论上可以在检测到 FINISH 的同时停止非流式调用，重新发起流式调用。
  → **缓解**: 实际上不额外增加调用——在 `_call_llm_with_retry` 中检测到 Action 行包含 FINISH 时，不返回完整响应而是切换到 stream=True 重新调用同一 prompt。代价是一次额外 LLM 调用（≈2-3s）。权衡：流式体验 >> 多等一次调用。
