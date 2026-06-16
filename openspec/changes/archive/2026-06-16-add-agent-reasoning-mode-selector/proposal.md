## Why

后端已完整实现 ReAct/CoT/none 三种推理模式（`server.py:1931-2011`、`raganything/agentic_rag.py`），通过 `QueryRequest.agent_mode` 参数控制。但前端智能体创建/编辑表单和对话页面完全没有暴露推理模式选项，用户无法在前端感知或切换推理模式。这导致后端能力对前端用户完全不可见，阻碍了 ReAct/CoT 推理模式的实际使用。

## What Changes

- 智能体配置模型新增 `agent_mode` 字段（默认 `"none"`），持久化到 `agent_meta.json`
- `AgentCreateRequest` / `AgentUpdateRequest` 新增 `agent_mode` 可选字段
- 智能体流式查询接口（`/api/agents/{id}/query/stream`）根据智能体配置的 `agent_mode` 选择普通流式或 AgenticRAG 流式路径
- 前端智能体创建/编辑表单（AgentsPage.jsx）新增推理模式下拉选择器
- 前端智能体对话页面（AgentChatPage.jsx）头部新增推理模式切换按钮组
- 前端 `api.js` 的 `query` 方法支持传递 `agent_mode` 参数

## Capabilities

### New Capabilities

- `agent-reasoning-mode-config`: 智能体推理模式配置 — 在 AgentConfig 中持久化 agent_mode，创建/更新 API 接受 agent_mode 字段，流式查询接口根据配置选择推理路径
- `frontend-reasoning-mode-selector`: 前端推理模式选择器 — 在智能体创建/编辑表单和对话页面中提供 ReAct/CoT/none 三种模式的可视化选择

### Modified Capabilities

<!-- No existing spec requirements are changing. These are purely additive capabilities. -->

## Impact

- **Backend**: `server.py` — `AgentCreateRequest`、`AgentUpdateRequest`、`AgentConfig`、agent query stream endpoint
- **Backend**: Agent manager — 持久化/读取 `agent_mode` 到 `agent_meta.json`
- **Frontend**: `AgentsPage.jsx` — 创建/编辑表单新增推理模式下拉框
- **Frontend**: `AgentChatPage.jsx` — 头部模式选择器新增推理模式按钮组，流式查询传递 `agent_mode`
- **Frontend**: `api.js` — `query` 方法支持 `agent_mode` 参数
- **Data**: `agent_meta.json` — 每个智能体新增 `agent_mode` 字段（默认 `"none"`，向后兼容）
