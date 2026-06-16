## 1. SSE 事件解析

- [x] 1.1 `AgentChatPage.jsx` `handleSSEEvent` case 'thinking': 检测 event.thought 字段，若存在则将 `{step, thought, action, observation, elapsed_ms}` 整体存入 thinking 数组；否则保持现有 content 字符串逻辑

## 2. 思考面板渲染

- [x] 2.1 `AgentChatPage.jsx` 思考面板渲染循环: 检测 step 是否为对象，若是则分行渲染 `🧠 思考: {step.thought}` `🔧 行动: {step.action}` `📋 观察: {step.observation}`；字符串则保持现有 `▸ {step}` 格式

## 3. 验证

- [ ] 3.1 重启服务，ReAct 模式提问，确认对话区域出现思考过程面板且内容正确
- [ ] 3.2 CoT 模式提问，确认思考面板展示各推理步骤
- [ ] 3.3 普通模式提问，确认思考面板行为不变（回归）
