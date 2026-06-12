# Manufacturing True Streaming

## Purpose

AgenticRAG 的 FINISH 步骤支持真流式 LLM token 输出，替代"完整推理后分块重放"的伪流式模式。QAEngine 新增 `answer_stream()` async generator 供 SSE 端点使用。

## Requirements

### Requirement: AgenticRAG 支持 FINISH 步流式输出
AgenticRAG SHALL 提供 `run_stream()` 方法，在 ReAct 循环的非 FINISH 步骤保持完整解析，在检测到 FINISH 动作时切换到 LLM stream 模式并逐 token 产出。

#### Scenario: 非 FINISH 步完整解析
- **WHEN** AgenticRAG 执行搜索/计算等工具调用步骤
- **THEN** 系统 SHALL 等待完整 LLM 响应后解析 Thought/Action/Action Input，产出 `{"type":"thinking",...}` 事件

#### Scenario: FINISH 步真流式
- **WHEN** LLM 响应中检测到 `Action: FINISH`
- **THEN** 系统 SHALL 以 `stream=True` 重新调用 LLM，逐 token yield `{"type":"token","content":"<token>"}` 事件

#### Scenario: backward-compatible run()
- **WHEN** 调用方使用 `run()` 方法
- **THEN** 行为与改造前完全一致：FINISH 步等待完整响应，返回 `AgentResult`

### Requirement: QAEngine 提供 answer_stream() 流式接口
QAEngine SHALL 提供 `answer_stream(query)` async generator，yield 结构化事件字典，供 SSE 端点逐事件转发。

#### Scenario: 流式产出 thinking 事件
- **WHEN** AgenticRAG 执行非 FINISH 步骤
- **THEN** answer_stream SHALL yield `{"type":"thinking","step":N,"thought":"...","action":"search"}`

#### Scenario: 流式产出 token 事件
- **WHEN** AgenticRAG 进入 FINISH 步流式输出
- **THEN** answer_stream SHALL 逐 token yield `{"type":"token","content":"<token>"}`

#### Scenario: 流式完成事件含后处理结果
- **WHEN** 流式 token 全部输出完毕
- **THEN** answer_stream SHALL 执行图片匹配和引用溯源，最后 yield `{"type":"done","images":[...],"citations":[...],"confidence":0.X}`

### Requirement: 制造 QA 流式端点真流式
`/api/manufacturing/qa/stream` SHALL 使用 `QAEngine.answer_stream()` 的 async generator 逐事件转发 SSE，不再使用 50 字符分块伪流式。

#### Scenario: SSE 事件序列
- **WHEN** 用户通过 `/api/manufacturing/qa/stream` 发起流式问答
- **THEN** SSE 事件序列 SHALL 为：`thinking`(N条) → `token`(N条) → `done`(1条)

#### Scenario: 首 token 延迟
- **WHEN** AgenticRAG 完成检索步骤进入 FINISH 步
- **THEN** 首 token SHALL 在 FINISH 步 LLM 开始流式输出后的 200ms 内到达客户端
