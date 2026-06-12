## 1. AgenticRAG 增强 — 支持自定义 system_prompt

- [x] 1.1 给 `AgenticRAG.__init__` 新增 `system_prompt_override` 参数，允许覆盖 ReAct/CoT 默认 system prompt
- [x] 1.2 修改 `_build_react_prompt()` 和 `_build_cot_prompt()`：当 system_prompt_override 不为空时，角色身份部分使用覆盖值，工具描述和推理格式部分保持不变

## 2. QAEngine 接入 AgenticRAG

- [x] 2.1 在 `QAEngine.__init__` 中创建 `AgenticRAG` 实例：`mode="react"`, `max_steps=3`, `system_prompt_override=制造领域 prompt`
- [x] 2.2 注册 `SearchTool`，默认 `query_mode="rrf"`，绑定制造智能体使用的 RAGAnything 实例
- [x] 2.3 修改 `QAEngine.answer()`：调用 `self.agentic_rag.run(query)` 替代 `_retrieve()` + `_generate()`
- [x] 2.4 在 `answer()` 中保留后处理：匹配 `relevant_images`、提取 `citations`、构造 `AgentResponse`
- [x] 2.5 将 `AgentResult.trace` 转换为 `AgentResponse.trace` 字段（新增），保持向后兼容
- [x] 2.6 移除废弃方法：`_retrieve()`, `_generate()`, `_no_llm_response()`, `_fallback_response()`（逻辑由 AgenticRAG 覆盖）
- [x] 2.7 保留不变的方法：`_match_relevant_images()` 及三级匹配、`_estimate_confidence()`、`SourceTracer`

## 3. Server 端点适配

- [x] 3.1 修改 `/api/manufacturing/qa` 端点：调用改造后的 `QAEngine.answer()`，返回 `AgentResponse`（含 trace）
- [x] 3.2 修改 `/api/manufacturing/qa/stream` 端点：SSE 格式先输出 `{"type":"thinking","step":N,"content":"thought"}` 再输出 `{"type":"answer","content":"answer文字"}`
- [x] 3.3 确保 `AgenticRAG` 实例从 server 的 `LLM_MODEL` / API_KEY 等环境变量正确初始化

## 4. 前端适配

- [x] 4.1 在 `ManufacturingAgentPage.jsx` 中展示推理轨迹：每个 thought step 显示为可折叠的思考卡片
- [x] 4.2 适配流式 SSE 消息解析：区分 `type: "thinking"` 和 `type: "answer"` 事件
- [x] 4.3 保留现有的代码解析和故障诊断 Tab 不变

## 5. 测试验证

- [x] 5.1 更新 `test_mfg_api.py`：验证新 `/api/manufacturing/qa` 返回含 trace 的 AgentResponse
- [x] 5.2 添加 ReAct 推理流程的单元测试：验证多步检索、工具调用、max_steps 上限
- [x] 5.3 端到端测试：上传制造文档 → 制造 QA 提问 → 验证引用溯源和图片匹配仍正常工作
- [x] 5.4 性能测试：确保制造 QA 多步推理延迟在可接受范围内（目标 < 10s，当前单步约 3-5s）
