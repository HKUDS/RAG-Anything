## Context

后端在 server.py agent_query_stream 的 ReAct/CoT 路径中发送结构化 thinking 事件。ReAct 路径 (line ~1815) 发送 `{type:'thinking', step, thought, action, observation, elapsed_ms}`，CoT 路径 (line ~1836) 发送 `{type:'thinking', step, thought, elapsed_ms}`。前端 `handleSSEEvent` 只检查 `event.content`，导致结构化事件被丢弃。

## Decisions

### Decision 1: thinking 数组支持混合类型

**现状**: `thinking` 数组元素均为字符串，通过 `[...(m.thinking || []), content]` 追加。

**修改**: 支持字符串（普通模式）和对象（ReAct/CoT）混合存储。`handleSSEEvent` 中检测 `event.thought` 存在性来区分格式。

### Decision 2: 结构化步骤渲染

**选择**: 使用 emoji 标签分行展示，不引入新的 UI 组件。

```
╭─────────────────────────────────╮
│ 🧠 思考 │ 需要检索知识库中关于...    │
│ 🔧 行动 │ search                   │
│ 📋 观察 │ 找到6个功能模块...        │
╰─────────────────────────────────╯
```

**理由**: 复用现有折叠面板组件，最小改动。emoji 标签比新增 CSS 类更直观。
