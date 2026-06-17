## Context

RAG-Anything 当前查询链路完全无状态：每个请求独立检索、独立生成，不感知之前的对话。`query_history`（server.py:202）记录 Q&A 到 `query_history.json` 但仅用于历史回放展示，从未注入到 LLM prompt 或 `rewrite_query()` 中。`rewrite_query()`（query.py:1303）已预留 `history` 参数但调用方未传入。

用户需求：同一会话中，后续提问应能感知前文（如解析代词"这个""它"），实现多轮上下文感知的 RAG 查询。

### 约束
- 不引入新外部依赖（用标准库 json + 项目已有设施）
- 向后兼容：不带 `thread_id` 的请求保持单轮行为
- 用户隔离：每个用户的会话独立（基于 JWT `current_user["id"]`）
- 不影响检索质量：历史上下文仅注入 LLM 生成阶段，不污染向量检索 query

## Goals / Non-Goals

**Goals:**
- 按 `thread_id` 分组的对话历史管理，支持创建/列出/删除会话
- 查询时自动将最近 N 轮历史注入 LLM prompt（对话上下文区 + 检索文档区 分离）
- 查询改写时传入历史上下文，实现指代消解（"这个" → "PLC故障码E001"）
- 持久化到 `conversations.json`，服务器重启不丢失
- 可配置的历史轮数和 token 预算

**Non-Goals:**
- 不引入 SQLite/Redis 等新存储引擎（本期用 JSON 文件，后续可迁移）
- 不实现向量化的长期记忆检索（不建 history embedding 索引）
- 不修改前端 UI（仅通过 API 支持，前端适配另开 change）
- 不涉及文档级权限、用户 RBAC 变更
- 不修改故障诊断的多轮对话（已有独立 session 机制）

## Decisions

### 1. 新增 `ConversationManager` 类

**选择**：在 `raganything/query.py` 中新增独立类，而非内嵌到 `QueryMixin` 或 `server.py`

**理由**：
- 单一职责：会话管理与查询逻辑分离
- 可测试：独立类易于单元测试
- 可复用：后续前端直接通过 API 调用，也可被其他模块复用

```python
class ConversationManager:
    def __init__(self, storage_path: str, max_rounds: int = 3, max_tokens: int = 2000)
    async def get_or_create_thread(self, user_id: str, thread_id: str = None, title: str = "新对话") -> Thread
    async def add_message(self, thread_id: str, role: str, content: str) -> None
    async def get_context(self, thread_id: str, current_query: str = "") -> ConversationContext
    async def list_threads(self, user_id: str) -> list[ThreadSummary]
    async def delete_thread(self, thread_id: str) -> bool
```

**替代方案**：直接用 `query_history` + `thread_id` 字段改造 → 拒绝，因为 `query_history` 是全局平铺的，按 thread 分组查询效率低且语义混乱。

### 2. 存储格式

**选择**：单文件 JSON `conversations.json`

```json
{
  "threads": {
    "th_a1b2c3": {
      "id": "th_a1b2c3",
      "user_id": "admin",
      "title": "PLC故障诊断",
      "created_at": "2026-06-17T10:30:00",
      "updated_at": "2026-06-17T10:35:00",
      "messages": [
        {"role": "user", "content": "PLC故障码E001是什么意思？", "timestamp": "..."},
        {"role": "assistant", "content": "E001表示...", "timestamp": "..."}
      ]
    }
  }
}
```

**理由**：与现有 `query_history.json` 一致的技术栈，无需新依赖；读写锁用 `asyncio.Lock` 保证并发安全。

**替代方案**：SQLite → 更适合大规模部署，但本期保持简单，JSON 文件在会话数 < 1000 时性能足够。

### 3. Prompt 模板结构

**选择**：在现有 prompt 中插入对话历史区，与检索文档区分离

```
## 对话历史
用户: PLC故障码E001是什么意思？
助手: E001表示电机过载保护触发...

## 检索到的相关文档
[Doc 1] (sources: ...)
...

## 当前问题
这个故障怎么解决？

请基于以上对话历史和检索文档回答问题...
```

**关键设计点**：
- 历史区只放最近 `max_rounds` 轮
- 历史总 token 数超过 `max_tokens` 时从旧到新截断
- 历史区在检索文档区之前，让 LLM 先理解上下文再看文档

**替代方案**：把历史拼接到 query 字符串中 → 拒绝，会污染检索查询的语义。

### 4. 查询改写集成点

**选择**：在 server.py 中 `rewrite_query()` 调用前，从 `ConversationManager` 取历史传入

```python
# 改造前
rewritten_query = await rewrite_query(req.query, instance.llm_model_func, ...)

# 改造后
history = await conversation_manager.get_context_for_rewrite(thread_id)
rewritten_query = await rewrite_query(
    req.query, instance.llm_model_func,
    history=history, api_key=API_KEY, base_url=BASE_URL,
)
```

### 5. API 变更

**新增端点**：
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/conversations` | 列出当前用户的会话 |
| POST | `/api/conversations` | 创建新会话 |
| DELETE | `/api/conversations/{thread_id}` | 删除会话 |

**修改端点**：
- `POST /api/query` — `QueryRequest` 增加可选字段 `thread_id: str = ""`
- `POST /api/query/stream` — 同上

向后兼容：不传 `thread_id` 时行为与当前完全一致（单轮模式）。

### 6. 安全设计（Security Architect 审核）

- **用户隔离**：`ConversationManager` 所有操作基于 `current_user["id"]` 过滤，用户 A 无法访问用户 B 的会话
- **输入长度限制**：单条消息 max 10000 字符，thread title max 100 字符
- **会话数上限**：每用户最多 50 个活跃会话，超过后拒绝创建（防滥用）
- **并发安全**：`asyncio.Lock` 保护读写 `conversations.json`

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| JSON 文件并发写入冲突 | `asyncio.Lock` 全局锁，单进程部署足够 |
| 大对话历史撑爆 prompt token 上限 | `CONVERSATION_MAX_TOKENS` 自动截断旧消息 |
| 注入的历史可能干扰检索语义 | 历史仅用于 prompt 生成阶段和 query rewrite，不参与向量检索 |
| 多用户高并发下 JSON 文件性能瓶颈 | 当前用户量下无问题；后续可迁移 SQLite |

## Migration Plan

1. 部署新代码，`conversations.json` 自动创建
2. 旧的 `query_history.json` 保留不删除（历史记录仍可通过 API 查询）
3. 不传 `thread_id` 的旧客户端行为不变（向后兼容）
4. 无需数据库迁移脚本

## Open Questions

- 是否需要在历史中同时存储检索到的文档引用？当前设计只存 Q&A 文本
- 前端会话 UI 何时实现？（建议另开 change）
