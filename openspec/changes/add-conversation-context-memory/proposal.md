## Why

RAG-Anything 当前每个查询是独立无状态的——前一轮问"PLC故障码E001是什么意思？"，下一轮问"这个故障怎么解决？"时，系统无从知晓"这个"指代什么。`query_history` 仅用于前端展示和历史记录回放，从未注入到 LLM prompt 或查询改写流程中，导致多轮对话中代词解析失败、上下文断裂。

## What Changes

- **新增会话级对话历史管理**：按 `thread_id` 分组存储对话历史，替代全局平铺的 `query_history`，支持创建/切换/删除会话
- **查询时注入历史上下文**：在 `/api/query` 和流式端点中将最近 N 轮对话历史注入 LLM prompt，使模型能理解指代和延续话题
- **查询改写接入历史**：`rewrite_query()` 调用时传入对话历史，将"这个怎么修"改写为"PLC故障码E001怎么修"
- **Prompt 模板改造**：增加对话历史区域，与检索文档区域分离，防止历史信息污染检索结果
- **可配置参数**：`CONVERSATION_MAX_ROUNDS`（默认 3）、`CONVERSATION_MAX_TOKENS`（默认 2000）控制历史注入量
- **持久化存储**：对话历史持久化到 `conversations.json`（单文件 JSON，与现有 `query_history.json` 并行），后续可迁移到 SQLite

## Capabilities

### New Capabilities
- `conversation-context-memory`: 多轮对话上下文记忆——会话管理、历史注入 prompt、查询改写联动、持久化

### Modified Capabilities
<!-- No existing specs need requirement-level changes. Implementation changes to query flow are internal. -->

## Impact

| 受影响的组件 | 变更类型 |
|-------------|---------|
| `server.py` — `/api/query`, `/api/query/stream` 端点 | 注入历史上下文、thread_id 参数 |
| `server.py` — 新增 `/api/conversations` CRUD 端点 | 新增 |
| `raganything/query.py` — `rewrite_query()` 调用点 | 传入 history 参数 |
| `raganything/query.py` — RRF prompt 构建 | 增加对话历史区域 |
| `raganything/query.py` — 新增 `ConversationManager` 类 | 新增 |
| `raganything/prompt.py` / `raganything/prompts_zh.py` | 模板扩展 |
| `query_history.json` → `conversations.json` | 存储格式变更（保留旧文件不迁移） |
| 前端 `frontend/` | 会话列表 UI、thread_id 传递（可选，向后兼容） |
