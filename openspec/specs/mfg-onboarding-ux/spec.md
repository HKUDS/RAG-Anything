# Manufacturing Onboarding UX

## Purpose

为制造智能体前端页面提供引导性空状态组件和工作流指引，帮助首次使用的用户理解数据导入→知识图谱→智能问答的使用流程。

## ADDED Requirements

### Requirement: Dashboard 数据空状态指引
当仪表盘无数据时，Dashboard 页面 SHALL 展示引导性空状态，包含三步工作流指引和直接跳转按钮。

#### Scenario: 仪表盘首次加载无数据
- **WHEN** 仪表盘加载完成且所有统计指标均为空或 0
- **THEN** 页面 SHALL 展示三步指引卡片：① 导入数据 → ② 构建知识图谱 → ③ 开始智能问答，每步附带跳转到对应页面的按钮

#### Scenario: 仪表盘有部分数据
- **WHEN** 仪表盘加载后部分统计有值但非全零
- **THEN** 页面 SHALL 隐藏引导卡片，正常展示数据统计

### Requirement: Agent 页面 Tab 空状态指引
制造智能体页面的各功能 Tab 在无历史消息时 SHALL 展示功能说明和示例操作。

#### Scenario: QA Tab 空状态
- **WHEN** 用户首次进入 QA Tab 且无历史对话
- **THEN** 页面 SHALL 展示"输入你的制造领域问题，智能体将基于知识库回答"提示，并提供 3 个可点击的示例问题（点击后直接发送）

#### Scenario: Code Parser Tab 空状态
- **WHEN** 用户切换到代码解析 Tab 且未输入代码
- **THEN** 页面 SHALL 展示 GCodeEditor 组件和简短的使用说明文字

#### Scenario: Fault Diagnosis Tab 空状态
- **WHEN** 用户首次进入故障诊断 Tab 且无诊断会话
- **THEN** 页面 SHALL 展示"描述设备故障现象"提示，并提供 3 个可点击的示例故障描述

### Requirement: 快捷提问按钮可靠触发
页面中的快捷提问按钮 SHALL 通过直接传参调用发送函数，而非依赖 setTimeout 竞态条件。

#### Scenario: 快捷提问按钮点击
- **WHEN** 用户点击预设问题按钮
- **THEN** 发送函数 SHALL 直接使用按钮文本作为参数调用，消息立即出现在对话列表中

#### Scenario: 快捷提问与手动输入不冲突
- **WHEN** 用户在输入框中已输入文字但未发送，随后点击快捷提问按钮
- **THEN** 系统 SHALL 清空输入框并以快捷提问文本发送，输入框中的未发送内容被丢弃
