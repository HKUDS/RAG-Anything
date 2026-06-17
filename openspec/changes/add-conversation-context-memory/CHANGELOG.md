# RAG-Anything 智能体上下文记忆功能 — 变更日志

**Date**: 2026-06-17  
**Branch**: `feature/custom-enhancements`  
**Commit**: [`16168c6`](https://github.com/619916cgh/RAG-Anything/commit/16168c6)

---

## 一、诊断结论

| 问题 | 位置 | 现象 |
|------|------|------|
| 对话历史仅记录不注入 | `server.py:202` query_history → 仅前端展示 | 多轮对话无上下文 |
| rewrite_query 接受 history 但未传入 | `query.py:1303` / `server.py:2372` | 指代词"这个""它"无法消解 |
| LLM prompt 无历史区 | `query.py:355` | 模型只看到 `检索文档 + 当前问题` |
| Agent 系统同样缺陷 | `server.py:2015` run_stream(req.query) | 有 ConversationThread 但从未传给 LLM |

**根因**: 历史数据完整存在于 `query_history.json` 和 `agent_conversations/*.json` 中，但查询流程从未将其注入 prompt。

---

## 二、新增能力

### 2.1 ConversationManager（多轮对话记忆引擎）

**位置**: `raganything/query.py`

```
┌─────────────────────────────────────┐
│         ConversationManager         │
│                                     │
│  get_or_create_thread(user, id)     │
│  add_message(thread, role, content) │
│  get_context(thread) → prompt 文本  │
│  get_context_for_rewrite(thread)    │
│  list_threads(user) → 会话列表      │
│  delete_thread(thread)              │
│                                     │
│  _load() / _save() → JSON 持久化   │
│  asyncio.Lock 并发保护              │
│  token 预算 / 轮数限制 / 用户隔离   │
└─────────────────────────────────────┘
```

**数据模型**:
- `ThreadSummary` — 会话列表摘要（id, title, 消息数, 时间）
- `ConversationContext` — 注入 prompt 的上下文（文本 + 元数据）
- `Thread` — 完整会话数据（user_id, messages[]）

### 2.2 查询流程（3 条路径全覆盖）

```
用户请求 (thread_id)
       │
       ├── 1. RAG 端点 /api/query
       │     ├→ rewrite_query(query, history)  ← 指代消解
       │     ├→ RAG 检索
       │     └→ prompt = 历史区 + 检索区 + 问题
       │
       ├── 2. Agent ReAct /api/agents/{id}/query/stream
       │     └→ agentic.run_stream("历史\n\n问题")
       │
       ├── 3. Agent CoT /api/agents/{id}/query/stream
       │     └→ agentic.run_with_context(query, "历史\n\n检索文档")
       │
       └── 4. Agent 普通 RAG
             └→ prompt = 历史区 + 检索区 + 问题
```

**Prompt 结构**:
```
## 对话历史
用户: PLC故障码E001是什么意思？
助手: E001表示电机过载保护触发...
用户: 这个故障怎么解决？

## 检索内容
[Doc 1] (sources: ...)
电机过载故障处理流程如下...

## 问题
它有哪些常见原因？

## 回答要求
- 结合对话历史理解上下文，解析指代词
- 从检索内容提取事实和数据
```

### 2.3 新增 API

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/conversations` | 列出当前用户会话 |
| `POST` | `/api/conversations` | `{title}` → 创建会话 |
| `DELETE` | `/api/conversations/{thread_id}` | 删除会话（归属校验） |
| `POST` | `/api/query` | 新增 `thread_id` 字段 |
| `POST` | `/api/query/stream` | 新增 `thread_id` 字段 |

### 2.4 Prompt 模板

| 模板 | 文件 |
|------|------|
| `PROMPTS["CONVERSATION_CONTEXT_TEMPLATE"]` (EN) | `raganything/prompt.py` |
| `PROMPTS_ZH["CONVERSATION_CONTEXT_TEMPLATE"]` (ZH) | `raganything/prompts_zh.py` |

---

## 三、环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `CONVERSATIONS_FILE` | `./conversations.json` | 会话存储路径 (RAG 端点) |
| `CONVERSATION_MAX_ROUNDS` | `3` | 注入 prompt 的最大历史轮数 |
| `CONVERSATION_MAX_TOKENS` | `2000` | 历史最大 token 预算 |
| `CONVERSATION_MAX_PER_USER` | `50` | 每用户最大会话数 |
| `ENABLE_QUERY_REWRITE` | `false` | 开启查询改写（需设为 true 才生效） |

---

## 四、安全设计

| 措施 | 实现 |
|------|------|
| 用户隔离 | 会话按 `user_id` 过滤，A 不可见 B 的会话 |
| 并发安全 | `asyncio.Lock` 保护 JSON 文件读写 |
| 输入限制 | 单条消息 ≤ 10000 字符，title ≤ 50 字符 |
| 数量上限 | 每用户 ≤ 50 个会话，防止资源滥用 |
| 向后兼容 | 不传 `thread_id` 完全保持单轮行为 |

---

## 五、测试结果

```
14/14  test_conversation_memory.py    ← 会话 CRUD、截断、隔离、持久化
22/22  test_agent_*.py                ← 无回归
56/56  test_core_modules + test_auth  ← 无回归
─────────────────────────────────
92 passed, 1 skipped — all green
```

---

## 六、变更文件清单

| 文件 | 类型 | 行数 |
|------|------|------|
| `raganything/query.py` | 新增 ConversationManager | +260 |
| `server.py` | API + 查询注入 | +245 |
| `tests/test_conversation_memory.py` | 单元测试 | +213 |
| `openspec/changes/add-conversation-context-memory/proposal.md` | 提案 | +33 |
| `openspec/changes/add-conversation-context-memory/design.md` | 设计 | +161 |
| `openspec/changes/add-conversation-context-memory/specs/.../spec.md` | 规格 | +112 |
| `openspec/changes/add-conversation-context-memory/tasks.md` | 任务 | +44 |
| `raganything/prompt.py` | 英文模板 | +10 |
| `raganything/prompts_zh.py` | 中文模板 | +10 |

---

## 七、OpenSpec 变更链路

```
proposal → design + specs → tasks → implement → verify
   ✅         ✅     ✅       ✅        ✅         ✅
```

🔗 [OpenSpec 变更目录](https://github.com/619916cgh/RAG-Anything/tree/feature/custom-enhancements/openspec/changes/add-conversation-context-memory)
