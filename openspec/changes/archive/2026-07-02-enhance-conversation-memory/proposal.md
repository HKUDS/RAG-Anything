## Why

当前智能体对话记忆系统只能做简单的"截断式"上下文注入——按轮数/Token粗暴截断对话历史后拼入Prompt。这个问题导致三个后果：(1)长对话必然"失忆"，早期上下文被永久丢弃；(2)Prompt构建逻辑在三个模式（RAG/ReAct/CoT）中各写一套，难以维护；(3)Claude Code层的MEMORY.md索引不完整，2/3记忆文件失效。现在是做这个改进的好时机——PG迁移已稳定，底层存储不再是瓶颈，可以在稳固的地基上构建更智能的记忆层。

## What Changes

### Phase 0: Claude Code 记忆修复
- 补全 MEMORY.md 索引，修复 2 个孤儿记忆文件（`openspec-scheduling-integration.md`、`parallel-agent-code-review.md`）

### Phase 1-2: 统一 Prompt 构建管线 + 上下文分层注入
- 新建 `PromptBuilder` 类，统一三种模式（RAG/ReAct/CoT）的 Prompt 拼接逻辑
- 引入上下文分层模型：系统指令 > 用户画像 > 历史摘要 > 近期对话 > 检索结果 > 当前问题
- 消除 agent.py 中的三处 Prompt 拼接重复代码（约 60 行重复逻辑）

### Phase 3: 长对话自动摘要/压缩
- 新增异步摘要生成机制：当对话历史超过阈值时，自动将早期轮次压缩为摘要
- 注入层变为"摘要 + 近期对话"两层结构，替代纯截断
- 摘要持久化到 PG，避免重复生成
- 新增 `CONVERSATION_SUMMARY_ENABLED`、`CONVERSATION_SUMMARY_TRIGGER_ROUNDS` 配置项

## Capabilities

### New Capabilities
- `context-layered-injection`: 上下文分层注入——Prompt 按优先级分层组装，每层有独立的开关和 token 预算
- `conversation-summary-compression`: 对话摘要压缩——长对话自动压缩早期轮次为摘要，解决纯截断导致的"失忆"问题

### Modified Capabilities
- `conversation-context-memory`: 对话历史注入机制从"纯截断"改为"摘要 + 近期对话"分层注入；Prompt 结构规范更新；持久化存储描述从 JSON 迁移到 PG

## Impact

### 受影响代码
| 文件 | 影响 |
|------|------|
| `raganything/routers/agent.py` | 重构 Prompt 拼接逻辑（~60行删除，改为调用 PromptBuilder） |
| `raganything/services/pg_state_repo.py` | 新增摘要存储方法 |
| `raganything/services/pg_agent_repo.py` | 新增 agent 对话摘要方法 |
| `raganything/prompt.py` / `prompts_zh.py` | 新增分层模板、摘要模板 |
| `memory/MEMORY.md` | 补全 2 个遗漏的索引条目 |
| `.env.example` | 新增摘要相关配置项 |
| `migrations/` | 可选的摘要存储 schema 变更 |

### 向后兼容
- 无 **BREAKING** 变更
- 摘要功能默认关闭（`CONVERSATION_SUMMARY_ENABLED=false`），需显式开启
- 旧对话（无摘要字段）降级为当前截断行为
