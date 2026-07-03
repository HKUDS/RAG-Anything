## Context

当前 RAG-Anything 的智能体对话提示词（Prompt）拼接逻辑分散在 `raganything/routers/agent.py` 的三个路径中——RAG 普通模式（L990-1037）、ReAct 模式（L560-579）、CoT 模式（L612-627）。三处各自独立拼接对话历史、图片上下文、检索结果，导致：
- 重复代码约 60 行，修改一处容易遗漏另外两处
- 上下文注入顺序固定，无法按场景调整（如 RAG 模式先放检索结果再放历史，ReAct 模式反之）
- 没有"用户画像"或"历史摘要"的插入位置——硬编码了 2 层（历史+检索），扩展需要改动多处

此外，当前历史注入采用纯截断策略（`max_rounds × 2` 条消息，token 预算内倒序截断），长对话的早期上下文被永久丢弃。对话越长，"失忆"越严重。

PG 存储层已稳定（`pg_agent_repo.py`），提供了可靠的持久化基础，可以在其之上构建更智能的记忆层。

## Goals / Non-Goals

**Goals:**
- 将三个模式的 Prompt 拼接逻辑统一到一个 `PromptBuilder` 类中，消除重复
- 引入上下文分层模型，每层有独立的开关（enabled）和 token 预算（max_tokens）
- 实现长对话自动摘要压缩：当历史消息超过阈值时，异步将早期轮次压缩为摘要文本
- 摘要持久化到 PG（`agent_conversations` 表新增 `summary` 字段），避免重复生成
- 补全 Claude Code 配置层的 MEMORY.md 索引

**Non-Goals:**
- 不引入跨对话"用户画像"（Profile）——那是 P4，需要独立的事实抽取管道
- 不改变现有 API 契约（请求/响应格式不变）
- 不引入向量化记忆或语义检索记忆——摘要仅作为文本注入
- 不做实时摘要（每条消息后都重新摘要）——只在触发阈值时异步生成

## Decisions

### Decision 1: PromptBuilder 统一构造器

**选择**：新建 `raganything/services/prompt_builder.py`，类 `PromptBuilder`，采用 Builder 模式。

```
┌──────────────────────────────────────────────────────────────┐
│                    PromptBuilder 管线                         │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  builder = PromptBuilder()                                   │
│    .system_instruction(sp)       # 层0: 系统指令（固定）       │
│    .context_layer({              # 层1: 用户画像（预留）       │
│        "name": "user_profile",                               │
│        "content": user_profile_text,                         │
│        "priority": 10,                                       │
│        "max_tokens": 500,                                    │
│        "enabled": bool(user_profile_text)                    │
│    })                                                        │
│    .context_layer({              # 层2: 对话摘要（P3新增）     │
│        "name": "summary",                                    │
│        "content": summary_text,                              │
│        "priority": 20,                                       │
│        "max_tokens": 1000,                                   │
│        "enabled": CONVERSATION_SUMMARY_ENABLED               │
│    })                                                        │
│    .context_layer({              # 层3: 近期对话              │
│        "name": "recent_history",                             │
│        "content": conv_history_text,                         │
│        "priority": 30,                                       │
│        "max_tokens": CONVERSATION_MAX_TOKENS,                │
│        "enabled": bool(conv_history_text)                    │
│    })                                                        │
│    .context_layer({              # 层4: 图片上下文            │
│        "name": "image_context",                              │
│        "content": img_section,                               │
│        "priority": 25,                                       │
│        "max_tokens": 2000,                                   │
│        "enabled": bool(img_section)                          │
│    })                                                        │
│    .retrieval_context(ctx)       # 层5: 检索结果              │
│    .user_query(query, cit_inst)  # 层6: 用户问题+引用指令     │
│    .build()                      # → 返回 (final_prompt, sp) │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**替代方案**：
- ❌ 在多处用 `_build_prompt()` 工具函数 → 消除了代码重复但没解决分层问题
- ❌ 用 Jinja2 模板 → 引入不必要的依赖，分层逻辑复杂，不如 Python 直写清晰
- ✅ PromptBuilder: 零外部依赖，直观的分层配置，易于测试和扩展

### Decision 2: 分层模型与 Token 预算分配

**选择**：每个 context layer 拥有独立的 `max_tokens` 预算。Builder 按 `priority` 升序组装（数字越小越靠前），超预算时从最低优先级层截断。

```
Token 预算分配策略（总预算 = max_tokens 参数，默认 8192）：

  ┌──────────────┬─────────────────────────────────────┐
  │ 层             │ 预算占比        │ 截断策略          │
  ├──────────────┼──────────────────┼──────────────────┤
  │ 0 System     │ 无预算限制       │ 不截断             │
  │ 1 Profile    │ 最多 500         │ 从开头截断         │
  │ 2 Summary    │ 最多 1000        │ 从开头截断         │
  │ 3 Recent msgs│ max_conv_tokens  │ 从旧消息截断       │
  │ 4 Images     │ 最多 2000        │ 减少/移除图片      │
  │ 5 Retrieval  │ 剩余预算         │ 从开头截断         │
  │ 6 Query      │ 无预算限制       │ 不截断             │
  └──────────────┴──────────────────┴──────────────────┘
```

截断顺序：先截检索结果（最便宜的信息），再截近期消息、图片、摘要。系统指令和用户问题永不截断。

### Decision 3: 摘要压缩机制

**选择**：阈值触发 + 异步生成 + 增量更新。

```
触发条件：
  messages_count > CONVERSATION_SUMMARY_TRIGGER_ROUNDS * 2（默认 5轮=10条）
  AND summary_enabled = true

摘要流程：
  ┌──────────┐     ┌──────────────┐     ┌──────────────┐
  │ 用户发消息 │ ──→ │ 检查消息数    │ ──→ │ 超过阈值？    │
  └──────────┘     │ 是否超阈值    │     │              │
                   └──────────────┘     └──┬───────┬───┘
                                          │ YES   │ NO
                                          ▼       ▼
                                   ┌──────────┐ ┌──────┐
                                   │ 异步调用   │ │ 跳过  │
                                   │ LLM 摘要  │ └──────┘
                                   └────┬─────┘
                                        ▼
                                   ┌──────────┐
                                   │ 写入 PG   │
                                   │ summary   │
                                   │ 字段      │
                                   └──────────┘

摘要 Prompt 模板：
  "请用 2-3 句话总结以下对话的核心内容和关键结论。只总结事实，不添加新信息。"
```

**关键设计决策**：
- 摘要操作**不影响当前请求的响应时间**——在用户收到回复后异步触发
- 首次摘要后，后续增量摘要：`新摘要 = LLM(旧摘要 + 新增消息)`
- 摘要生成失败（LLM 不可用等）时，当前截断行为不变，不阻塞用户交互
- 摘要文本存储到 `agent_conversations.summary` (TEXT, nullable) 和 `agent_conversations.summary_updated_at` (TIMESTAMPTZ)

**替代方案**：
- ❌ 简单截断（当前做法）→ 丢失信息
- ❌ 滑动窗口（保留最近 N 轮+随机采样历史）→ 实现简单但信息密度低
- ❌ 向量化记忆（用嵌入检索相关历史）→ 过度设计，适合 P4 考虑
- ✅ LLM 摘要压缩：信息压缩率高，与当前 LLM 调用模式一致，易于实现

### Decision 4: Data Model — 摘要持久化

**选择**：在 `agent_conversations` 表新增两个字段，通过 migration 添加。

```sql
ALTER TABLE agent_conversations
ADD COLUMN summary TEXT,
ADD COLUMN summary_updated_at TIMESTAMPTZ;
```

- `summary`: 压缩后的摘要文本，NULL 表示未生成
- `summary_updated_at`: 上次摘要更新时间，用于增量摘要判断
- 摘要不代替原始消息——消息完整保留，摘要仅作为 Prompt 注入的"快捷方式"

### Decision 5: P0 — MEMORY.md 索引修复

**选择**：直接补充 2 个遗漏条目，不改动现有记忆文件内容。

```
MEMORY.md 当前：
  - [no-auto-commit](no-auto-commit.md) — ...

MEMORY.md 修复后：
  - [no-auto-commit](no-auto-commit.md) — ...
  - [openspec-scheduling-integration](openspec-scheduling-integration.md) — ...
  - [parallel-agent-code-review](parallel-agent-code-review.md) — ...
```

这是最低风险的修复——两个文件已存在且内容有效，只是索引入口缺失导致系统无法加载。

## Risks / Trade-offs

| 风险 | 级别 | 缓解措施 |
|------|------|---------|
| 摘要内容失真（LLM 产生幻觉，压缩出错误信息） | 中 | 摘要模板强调"只总结事实"；摘要+近期消息双注入，不替代原始消息；默认关闭，用户选择开启 |
| 异步摘要失败导致摘要字段长期为 NULL | 低 | 每次新消息都检查是否需要摘要；失败时记录日志但不阻塞；下次触发时重试 |
| PromptBuilder 重构引入回归（三种模式 Prompt 行为变化） | 中 | 重构前后跑现有测试套件；Builder.build() 单元测试覆盖三种模式的 Prompt 输出对比 |
| Token 预算分配不合理导致某种模式下回答质量下降 | 低 | 每层预算可通过环境变量独立配置；默认值基于当前生产配置推导 |

## Migration Plan

1. **Phase 0**（独立部署）：修改 MEMORY.md → 即时生效，无依赖
2. **Phase 1-2**：部署新代码 + PromptBuilder → 三种模式 Prompt 行为应保持向后兼容
3. **Phase 3**：运行 migration 添加 summary 字段 → `CONVERSATION_SUMMARY_ENABLED=false` 默认关闭，手动开启
4. **回滚**：summary 字段可安全忽略（旧代码不读它）；PromptBuilder 可通过 feature flag 回退到旧的三分支拼接
