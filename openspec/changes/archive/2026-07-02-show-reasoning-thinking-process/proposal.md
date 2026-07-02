## Why

后端 ReAct/CoT 模式已在 SSE 中发送结构化 thinking 事件（`{type:"thinking", step, thought, action, observation, elapsed_ms}`），但前端 `handleSSEEvent` 的 `case 'thinking'` 只处理 `event.content` 字段。结构化事件中 `content` 为 undefined，导致 `if (content)` 为 false，整个 thinking 事件被静默丢弃。用户在任何模式下都看不到思考过程。

## What Changes

- **`AgentChatPage.jsx`**: `handleSSEEvent` 的 `case 'thinking'` 同时处理两种格式：`content` 字符串和结构化 `{thought, action, observation}` 对象，格式化为可读文本存入 `thinking` 数组
- **`AgentChatPage.jsx`**: 思考面板渲染改为检测 step 是否为对象，若是结构化数据则分行展示 Thought / Action / Observation 标签

## Capabilities

### New Capabilities

- `frontend-thinking-display`: 前端思考过程展示 — 解析结构化 thinking 事件并以 Thought/Action/Observation 标签分行渲染

### Modified Capabilities

<!-- No existing spec changes -->

## Impact

- **`frontend/src/pages/AgentChatPage.jsx`**: `handleSSEEvent`、thinking 面板渲染
- 后端无改动
