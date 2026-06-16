# Agent Reasoning Mode Configuration

## Purpose

将推理模式（agent_mode）纳入智能体配置模型，支持创建/更新时持久化，并确保流式查询接口根据配置选择正确的推理路径（普通 RAG 流式 vs AgenticRAG ReAct 流式）。

## Requirements

### Requirement: AgentConfig 包含 agent_mode 字段
AgentConfig 数据模型 SHALL 包含 `agent_mode` 字段，类型为 `str`，默认值为 `"none"`。该字段 SHALL 持久化到 `agent_meta.json` 中。

#### Scenario: 新建智能体默认无推理模式
- **WHEN** 创建新智能体且未指定 agent_mode
- **THEN** AgentConfig.agent_mode SHALL 默认为 `"none"`，向后兼容现有行为

#### Scenario: 持久化包含 agent_mode
- **WHEN** 智能体保存到 agent_meta.json
- **THEN** 每个 agent 对象的 JSON 中 SHALL 包含 `"agent_mode"` 字段

### Requirement: AgentCreateRequest 和 AgentUpdateRequest 接受 agent_mode
智能体创建/更新 API 的请求体 SHALL 接受可选字段 `agent_mode`，有效值为 `"react"`、`"cot"`、`"none"`。

#### Scenario: 创建时指定推理模式
- **WHEN** 向 `/api/agents` 发送 POST 请求，body 包含 `{"agent_mode": "react"}`
- **THEN** 创建的智能体 AgentConfig.agent_mode SHALL 为 `"react"`

#### Scenario: 更新时修改推理模式
- **WHEN** 向 `/api/agents/{id}` 发送 PUT 请求，body 包含 `{"agent_mode": "cot"}`
- **THEN** 智能体的 agent_mode SHALL 更新为 `"cot"`

#### Scenario: 不传 agent_mode 保持默认
- **WHEN** 创建或更新请求未包含 agent_mode
- **THEN** 智能体的 agent_mode SHALL 保持为 `"none"`（创建时）或维持原值（更新时）

### Requirement: 智能体流式查询接口根据 agent_mode 选择推理路径
`/api/agents/{agent_id}/query/stream` 端点 SHALL 读取智能体配置中的 `agent_mode`，当值为 `"react"` 时使用 AgenticRAG 流式推理路径，当值为 `"none"` 或 `"cot"` 时使用现有普通流式路径。

#### Scenario: agent_mode=none 走普通流式
- **WHEN** 智能体的 agent_mode 为 `"none"`
- **THEN** 流式查询 SHALL 使用现有的直接检索+流式 LLM 路径（现有行为不变）

#### Scenario: agent_mode=react 走 AgenticRAG 流式
- **WHEN** 智能体的 agent_mode 为 `"react"`
- **THEN** 流式查询 SHALL 初始化 AgenticRAG(mode="react")，通过 `run_stream()` 执行推理，产出 thinking/token/done SSE 事件

#### Scenario: agent_mode=cot 走 AgenticRAG 非流式
- **WHEN** 智能体的 agent_mode 为 `"cot"`
- **THEN** 流式查询 SHALL 初始化 AgenticRAG(mode="cot")，通过 `run()` 执行推理，将最终回答作为单个 token 事件产出

### Requirement: AgentQueryRequest 保留 agent_mode 覆盖能力
智能体流式查询的 `AgentQueryRequest` SHALL 保留可选的 `agent_mode` 字段，当请求中指定时覆盖智能体默认配置。

#### Scenario: 请求级覆盖
- **WHEN** 智能体配置 agent_mode="none"，但查询请求 body 包含 `{"agent_mode": "react"}`
- **THEN** 该次查询 SHALL 使用 "react" 模式
