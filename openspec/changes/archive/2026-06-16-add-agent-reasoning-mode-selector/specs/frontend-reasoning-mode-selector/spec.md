# Frontend Reasoning Mode Selector

## Purpose

在前端智能体管理界面中暴露推理模式选择器，让用户可以在智能体创建/编辑时配置默认推理模式，在对话页面中切换推理模式，并确保切换后实际推理行为随之改变。

## ADDED Requirements

### Requirement: 智能体创建/编辑表单包含推理模式选择器
智能体创建/编辑表单（AgentsPage.jsx）SHALL 包含推理模式（agent_mode）下拉选择器，选项为"无（直接回答）"、"ReAct 多步推理"、"CoT 逐步思考"，对应值 `"none"`、`"react"`、`"cot"`。

#### Scenario: 新建智能体默认选中"无"
- **WHEN** 打开新建智能体表单
- **THEN** 推理模式选择器 SHALL 默认选中 `"none"`

#### Scenario: 编辑智能体回显当前推理模式
- **WHEN** 打开编辑已有智能体表单
- **THEN** 推理模式选择器 SHALL 显示该智能体的 agent_mode 值

#### Scenario: 保存时发送 agent_mode
- **WHEN** 点击"创建智能体"或"保存修改"
- **THEN** API 请求 body SHALL 包含 `agent_mode` 字段

### Requirement: 智能体对话页面包含推理模式切换按钮
智能体对话页面（AgentChatPage.jsx）头部 SHALL 在现有检索模式按钮组旁新增推理模式按钮组，包含"普通"、"ReAct"、"CoT"三个选项。

#### Scenario: 切换推理模式
- **WHEN** 用户点击推理模式按钮（如"ReAct"）
- **THEN** 页面 SHALL 更新选中状态，后续发送的流式查询请求 SHALL 携带对应的 `agent_mode` 参数

#### Scenario: 推理模式与检索模式独立
- **WHEN** 用户切换推理模式
- **THEN** 检索模式（rrf/hybrid/local/global/naive）SHALL 不受影响，反之亦然

#### Scenario: ReAct 模式下展示思考过程
- **WHEN** 用户在 ReAct 模式下发送查询
- **THEN** 返回的 SSE `thinking` 事件 SHALL 在对话区域以折叠面板形式展示（复用现有思考过程展示逻辑）

#### Scenario: 普通模式下无思考过程
- **WHEN** 用户在 `"none"` 模式下发送查询
- **THEN** 对话区域 SHALL 不展示思考过程面板（仅直接流式输出回答）

### Requirement: 智能体列表卡片展示推理模式标签
智能体列表页（AgentsPage.jsx）的智能体卡片 SHALL 展示推理模式标签徽章，与现有的知识库、模型、检索模式标签并列。

#### Scenario: 卡片显示推理模式
- **WHEN** 智能体的 agent_mode 为 `"react"`
- **THEN** 卡片 SHALL 显示标签 `"ReAct"`（使用独特的颜色/图标以区别于检索模式标签）
