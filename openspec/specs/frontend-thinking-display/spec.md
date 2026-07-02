# Frontend Thinking Display

## Purpose

修复前端对 ReAct/CoT 结构化 thinking 事件的接收和展示，让用户能在对话页面看到推理思考过程。

## ADDED Requirements

### Requirement: 接收结构化 thinking 事件
`handleSSEEvent` 的 `case 'thinking'` SHALL 同时支持两种格式：字符串 `content`（普通模式）和结构化对象 `{step, thought, action, observation}`（ReAct/CoT 模式）。

#### Scenario: 普通模式 thinking 不变
- **WHEN** SSE 事件为 `{"type": "thinking", "content": "🔍 开始查询..."}`
- **THEN** 行为与现有版本一致，content 直接追加到 thinking 数组

#### Scenario: ReAct 结构化 thinking
- **WHEN** SSE 事件为 `{"type": "thinking", "step": 1, "thought": "需要检索...", "action": "search", "observation": "找到..."}`
- **THEN** event SHALL 被格式化为结构化对象 `{step, thought, action, observation}` 存入 thinking 数组

### Requirement: 思考面板结构化渲染
思考面板 SHALL 检测 thinking 条目类型：字符串直接显示，结构化对象以 Thought/Action/Observation 分行标签展示。

#### Scenario: 结构化步骤展示
- **WHEN** thinking 条目为 `{step: 1, thought: "...", action: "search", observation: "..."}`
- **THEN** 面板 SHALL 分行显示 `🧠 思考: ...` `🔧 行动: search` `📋 观察: ...`
