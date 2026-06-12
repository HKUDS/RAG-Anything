## 1. AgenticRAG 流式改造

- [x] 1.1 新增 `StreamEvent` dataclass：`type`、`step`、`thought`、`action`、`content`
- [x] 1.2 新增 `run_stream()` 方法：AsyncIterator[StreamEvent]
- [x] 1.3 非 FINISH 步复用 `_react_loop` 的解析逻辑，产出 `type="thinking"` 事件
- [x] 1.4 FINISH 步：检测到 `Action: FINISH` 后，以 `stream=True` 重新调用 `llm_func`，逐 token yield `type="token"` 事件
- [x] 1.5 `run()` 保持向后兼容，行为不变

## 2. QAEngine 流式接口

- [x] 2.1 新增 `answer_stream(query) -> AsyncIterator[dict]` 方法
- [x] 2.2 内部调用 `agentic_rag.run_stream(query)`，透传 thinking/token 事件
- [x] 2.3 流结束后执行图片匹配 + 引用溯源，yield `type="done"` 事件含 images/citations/confidence

## 3. Server 端点适配

- [x] 3.1 `/api/manufacturing/qa/stream` 改用 `engine.answer_stream()` 替代 `engine.answer()`
- [x] 3.2 SSE 事件格式与通用智能体 `/api/query/stream` 统一：`token` → `done`
- [x] 3.3 移除 50 字符分块 hack

## 4. 前端适配

- [x] 4.1 `ManufacturingAgentPage.jsx` 的 token 处理改为逐字追加（移除对 50 字符块的特殊处理）
- [x] 4.2 thinking 事件展示逻辑保持现有可折叠卡片组件不变
