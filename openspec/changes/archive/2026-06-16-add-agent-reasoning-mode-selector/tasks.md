## 1. Backend — AgentConfig 模型扩展

- [x] 1.1 `agent_manager.py`: 在 `AgentConfig` 中新增 `agent_mode: str = "none"` 字段（插入在 `query_mode` 之后，与其他检索配置并列）
- [x] 1.2 验证 `AgentConfig.model_dump()` 自动包含 `agent_mode`，`_save_agents()` 原子写入 `agent_meta.json` 时包含该字段

## 2. Backend — API 请求模型扩展

- [x] 2.1 `server.py`: `AgentCreateRequest` 新增 `agent_mode: str = "none"` 字段
- [x] 2.2 `server.py`: `AgentUpdateRequest` 新增 `agent_mode: Optional[str] = None` 字段
- [x] 2.3 `server.py`: `create_agent()` 中实例化 `AgentConfig` 时传入 `agent_mode=req.agent_mode`
- [x] 2.4 `server.py`: `update_agent()` 中 `req.model_dump()` 的 updates 自然包含 `agent_mode`（无需额外改动，现有 `setattr` 循环已处理）

## 3. Backend — 流式查询端点改造

- [x] 3.1 `server.py`: 检查 `AgentQueryRequest` 是否已有 `agent_mode` 字段，若无则新增 `agent_mode: Optional[str] = None`
- [x] 3.2 `server.py` `/api/agents/{agent_id}/query/stream`: 读取 `req.agent_mode or agent.agent_mode` 确定实际推理模式
- [x] 3.3 当 `agent_mode == "react"` 时：初始化 `AgenticRAG(mode="react")` → 注册 `SearchTool` → 调用 `run_stream()` → 产出 SSE thinking/token/done 事件
- [x] 3.4 当 `agent_mode == "cot"` 时：初始化 `AgenticRAG(mode="cot")` → 注册 `SearchTool` → 调用 `run()` → 将回答作为单个 token 事件 + done 事件产出
- [x] 3.5 当 `agent_mode == "none"` 或未设置时：保持现有流式路径不变

## 4. Frontend — 智能体表单推理模式选择器

- [x] 4.1 `AgentsPage.jsx`: `getDefaultForm()` 中新增 `agent_mode: 'none'`
- [x] 4.2 `AgentsPage.jsx`: `openEdit()` 中从 agent 对象提取 `agent_mode` 回填表单
- [x] 4.3 `AgentsPage.jsx`: `applyTemplate()` 中处理模板的 `agent_mode`
- [x] 4.4 `AgentsPage.jsx`: 在"默认查询模式"下拉框下方新增"推理模式"下拉框，选项：
  - `"none"` → "无（直接回答）"
  - `"react"` → "ReAct 多步推理"
  - `"cot"` → "CoT 逐步思考"

## 5. Frontend — 智能体卡片推理模式标签

- [x] 5.1 `AgentsPage.jsx`: 新增 `AGENT_MODE_LABELS` 映射 `{ none: '普通', react: 'ReAct', cot: 'CoT' }`
- [x] 5.2 `AgentsPage.jsx`: 在智能体卡片标签区新增推理模式标签，使用与检索模式不同的颜色（如 teal/cyan 系）

## 6. Frontend — 对话页面推理模式切换

- [x] 6.1 `AgentChatPage.jsx`: 新增 `REASONING_MODES` 数组 `[{ key: 'none', icon: MessageSquare, label: '普通' }, { key: 'react', icon: Brain, label: 'ReAct' }, { key: 'cot', icon: Layers, label: 'CoT' }]`
- [x] 6.2 `AgentChatPage.jsx`: 新增 `agentMode` 状态，从 `agent.agent_mode` 初始化
- [x] 6.3 `AgentChatPage.jsx`: 在检索模式按钮组旁新增推理模式按钮组，使用视觉分隔符区分
- [x] 6.4 `AgentChatPage.jsx`: `streamQuery()` 中 body 新增 `agent_mode: agentMode`

## 7. Frontend — API 工具函数更新

- [x] 7.1 `api.js`: `query()` 方法新增 `agentMode` 参数，添加 `agent_mode` 到请求 body

## 8. 验证

- [x] 8.1 测试创建新智能体时选择 "ReAct 多步推理"，确认 `agent_meta.json` 正确持久化
- [x] 8.2 测试编辑已有智能体，修改推理模式为 "CoT"，确认更新生效
- [x] 8.3 测试 ReAct 模式下发送查询，确认流式返回 thinking 事件且前端展示思考过程
- [x] 8.4 测试 CoT 模式下发送查询，确认返回完整回答
- [x] 8.5 测试普通模式下发送查询，确认行为与改前完全一致（回归测试）
- [x] 8.6 测试推理模式与检索模式独立切换，互不干扰
