## Context

制造智能体的 QA 引擎 (`qa_engine.py:QAEngine`) 当前是"检索→LLM 直出"的单步模式：固定以 `mode="rrf"` 检索，然后构造 prompt 调用 LLM 生成回答。通用智能体 (`agentic_rag.py:AgenticRAG`) 已实现完整的 ReAct/CoT 多步推理循环，支持 SearchTool、CalculatorTool、DBQueryTool、WebSearchTool 四种工具。两者共享相同的 LLM 和检索基础设施，但推理模式完全不同。

**现状架构**:
```
QAEngine.answer(query)
  → _retrieve(query)        # 硬编码 mode="rrf"
  → _match_relevant_images() # 三级图片匹配
  → _generate(query, docs)   # LLM 直出
  → AgentResponse
```

**目标架构**:
```
QAEngine.answer(query)
  → AgenticRAG.run(query)    # ReAct 多步推理
  → _match_relevant_images() # 保留图片匹配
  → enrich AgentResult with images + citations
  → AgentResponse (含 trace)
```

## Goals / Non-Goals

**Goals:**
- 制造 QA 获得多步推理能力，能自主决定检索次数、参数和策略
- 复用 `AgenticRAG` 和已有工具生态（SearchTool、CalculatorTool 等），消除代码重复
- 保留制造领域专有能力：三级图片匹配、引用溯源、制造专用 system prompt
- 前端展示 ReAct 推理轨迹（thought chain），提升可解释性

**Non-Goals:**
- 不修改故障诊断模块（`fault_diagnosis.py`）——它已有自己的多轮对话引擎
- 不修改代码解析模块（`code_parser.py`）——它是无状态的单次解析
- 不修改通用智能体的 AgenticRAG 引擎本身
- 不新增制造专用工具（本次仅复用已有工具）

## Decisions

### Decision 1: QAEngine 包装 AgenticRAG 而非替换
**选择**: `QAEngine` 内部持有 `AgenticRAG` 实例并委托调用，保留 `QAEngine` 作为制造领域的外观层。

**理由**:
- 保持向后兼容的 `QAEngine.answer()` 签名
- 制造专用的 system prompt、图片匹配、引用溯源逻辑挂载在 `QAEngine` 上
- 未来可添加制造专用工具（如 `ProcessSearchTool`）而不影响通用 AgenticRAG

**替代方案**: 废弃 `QAEngine`，直接在 server 端点中创建 `AgenticRAG` 实例。
**否决原因**: 丢失图片匹配和引用溯源能力；server 端点逻辑变重。

### Decision 2: 制造专用 system prompt 覆盖 AgenticRAG 默认 prompt
**选择**: 给 `AgenticRAG` 添加 `system_prompt` 参数，制造 QA 传入"智能制造教学专家"身份 prompt。

**理由**:
- 保持工具描述和 ReAct 格式指令（Thought/Action/...）不变
- 只替换角色身份和领域知识约束
- 改动最小（AgenticRAG 仅需新增一个参数）

### Decision 3: 图片匹配保留为后处理步骤
**选择**: `AgenticRAG.run()` 返回后，`QAEngine` 对最终答案执行图片匹配。

**理由**:
- 图片匹配依赖 LLM 生成答案中的图号引用和 caption 关键词
- 放在后处理位置不影响推理循环的步数限制
- 避免将图片匹配封装为工具带来的额外 LLM 调用开销

### Decision 4: 前端复用 AgenticRAG 的流式格式
**选择**: 制造 QA 流式端点输出与通用智能体一致的 SSE 格式（`{"type":"thinking","content":"..."}`），在 `AgentResponse` 中新增 `trace` 字段。

**理由**:
- 前端 `ManufacturingAgentPage.jsx` 可复用通用智能体已有的思考过程展示组件
- 格式一致 = 代码一致 = 维护成本低

## Risks / Trade-offs

- **[风险] AgenticRAG 多步推理增加延迟**: ReAct 模式每步至少一次 LLM 调用，总延迟可能是单步模式的 2-5 倍。
  → **缓解**: 制造 QA 默认 `max_steps=3`（通用为 5），且 `SearchTool` 单次返回足够上下文。
- **[风险] 检索质量可能下降**: 当前硬编码 `mode="rrf"` 是经过优化的；AgenticRAG 的 SearchTool 默认用 `mode="hybrid"`。
  → **缓解**: SearchTool 的 `query_mode` 可通过 AgentConfig 配置为 `"rrf"`。
- **[风险] 前端适配工作量**: `AgentResponse` 新增 `trace` 字段，前端需展示推理步骤。
  → **缓解**: 通用智能体对话页已有成熟的思考过程展示 UI，可直接复用组件。
