## Why

制造智能体当前的问答是"检索→LLM 直出"的单步模式，而通用智能体已具备 ReAct/CoT 多步推理 + 工具调用（SearchTool、CalculatorTool、DBQueryTool、WebSearchTool）。制造领域同样需要多步推理能力——例如先查工艺参数，再计算结果，最后查故障案例交叉验证。将两者统一可消除代码重复，让制造智能体复用已有的 AgenticRAG 引擎和工具生态。

## What Changes

- 制造智能体 QA 的 `QAEngine.answer()` 从单步 RRF 检索+LLM 生成改为调用 `AgenticRAG.run()` 多步推理循环
- 移除 `QAEngine._retrieve()` 和 `QAEngine._generate()` 中的单步 RRF 固定逻辑
- 保留制造专用的能力：三级图片匹配 (`_match_relevant_images`)、引用溯源 (`SourceTracer`)、制造领域 system prompt
- 保留制造专用的诊断和代码解析子模块独立不变
- 制造 QA 通过 `SearchTool` 使用 RRF 检索（与通用智能体一致），而非硬编码 `mode="rrf"`
- 前端制造智能体页面 (`ManufacturingAgentPage.jsx`) 的流式输出适配 `AgentResult` 格式（含 `trace` 推理轨迹）

## Capabilities

### New Capabilities
- `mfg-agentic-reasoning`: 制造 QA 引擎集成 AgenticRAG 多步推理（ReAct/CoT），支持工具调用、推理轨迹追踪、流式思考过程展示

### Modified Capabilities
- `rag-integration`: 制造 QA 的检索方式从内部固定 RRF 调用改为通过 SearchTool 接入 AgenticRAG 工具框架，检索参数由 Agent 自主决策

## Impact

- **Affected code**:
  - `raganything/manufacturing/agent/qa_engine.py` — 核心改造：移除单步检索+生成逻辑，接入 AgenticRAG
  - `server.py:2766/2783` — `/api/manufacturing/qa` 和 `/api/manufacturing/qa/stream` 适配新返回格式
  - `frontend/src/pages/ManufacturingAgentPage.jsx` — 展示推理轨迹 (thought chain)
- **Breaking changes**: `QAEngine.answer()` 返回的 `AgentResponse` 格式新增 `trace` 字段（含多步推理记录），前端需适配
- **Dependencies**: 无新增依赖，复用现有 `raganything.agentic_rag` 模块
