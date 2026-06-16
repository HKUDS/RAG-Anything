## Context

后端 `AgenticRAG` 引擎已完整支持 ReAct 和 CoT 两种推理模式（`raganything/agentic_rag.py`），`/api/query` 端点已支持 `agent_mode` 参数。但智能体全链路（配置模型 → API → 流式查询）和前端 UI 均未暴露推理模式选项。当前 `AgentConfig` 模型有 `query_mode`（检索模式）但没有 `agent_mode`（推理模式），前端 `AgentChatPage` 的模式按钮组只包含检索模式切换。

## Goals / Non-Goals

**Goals:**
- 将 `agent_mode` 纳入 `AgentConfig` 模型，持久化到 `agent_meta.json`
- `AgentCreateRequest` / `AgentUpdateRequest` 接受 `agent_mode` 字段
- `/api/agents/{id}/query/stream` 根据智能体的 `agent_mode` 选择推理路径
- 前端 `AgentsPage` 表单新增推理模式下拉选择器
- 前端 `AgentChatPage` 头部新增推理模式切换按钮组
- 前端 `api.query()` 方法支持 `agent_mode` 参数

**Non-Goals:**
- 不修改 `AgenticRAG` 核心引擎逻辑（已稳定）
- 不修改 `/api/query` 通用查询端点（已支持 agent_mode）
- 不改变现有智能体的默认行为（agent_mode 默认 `"none"`，完全向后兼容）
- 不在制造 QA 引擎中暴露 agent_mode 选择（制造 QA 固定使用 ReAct 兜底策略）

## Decisions

### Decision 1: agent_mode 默认值为 "none"

**选择**: `agent_mode` 字段默认 `"none"`。

**理由**: 向后兼容。现有智能体没有该字段，默认 `"none"` 确保已有智能体的行为完全不变。只有用户主动选择 ReAct/CoT 时才启用多步推理。

**替代方案**: 默认 `"react"` — 但会增加所有现有智能体的 token 消耗和延迟，风险不可控。

### Decision 2: AgenticRAG 在流式查询端点内按需初始化

**选择**: 在 `/api/agents/{agent_id}/query/stream` 的处理函数内，仅在 `agent_mode == "react"` 或 `"cot"` 时才导入并初始化 `AgenticRAG`。

**理由**: 
- 延迟导入避免普通模式下不必要的依赖加载
- 每次查询独立创建 AgenticRAG 实例，保证配置隔离
- 与 `/api/query` 端点的现有模式一致（`server.py:1956-1966`）

### Decision 3: CoT 模式在流式查询中退化为非流式

**选择**: `agent_mode="cot"` 时，调用 `AgenticRAG.run()`（非流式），将完整回答作为单个 token 事件发送。

**理由**: `AgenticRAG.run_stream()` 仅支持 mode="react"（`agentic_rag.py:163`），CoT 是一次性 LLM 调用。保持与 `AgenticRAG` 的实现约束一致。

**替代方案**: 在 CoT 回答生成后做字符级拆分逐 token 发送 — 增加了复杂性但用户体验差异很小（CoT 本身就是单次调用）。

### Decision 4: 前端推理模式与检索模式并列展示

**选择**: 在对话页面头部添加独立的推理模式按钮组，与检索模式按钮组并列。
**布局**: `[检索: 融合 | 智能 | 精确 | 全局 | 快速] → [推理: 普通 | ReAct | CoT]`

**理由**: 推理模式和检索模式是正交概念（见会话讨论），分开展示比合并更清晰，用户一眼能看出两层配置。

## Risks / Trade-offs

- **ReAct 多步推理延迟高**: ReAct 模式下每次查询可能需要 2-5 轮 LLM 调用 + 检索 → 通过步数限制（默认 5）和工具超时（30s）控制。前端展示思考过程让用户感知进度。
- **Token 消耗增加**: ReAct 多步推理显著增加 token 消耗 → 默认 `"none"` 避免意外消耗，需用户主动选择。
- **CoT 模式不支持图片匹配**: CoT 不走 SearchTool，无法触发制造 QA 的三级图片匹配 → 文档说明 CoT 适用于纯逻辑推理场景，制造领域推荐 ReAct。

## Migration Plan

1. **部署**: 代码部署后，所有现有智能体自动获得 `agent_mode: "none"`（通过默认值），行为不变
2. **回滚**: 前端组件纯增量添加；`AgentConfig.agent_mode` 为可选字段，移除代码后 agent_meta.json 中多余的字段不影响现有功能
3. **数据迁移**: 无需数据迁移，`agent_mode` 字段通过 Pydantic 默认值 `"none"` 自动填充
