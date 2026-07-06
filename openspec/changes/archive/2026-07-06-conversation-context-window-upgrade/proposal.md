## Why

当前多轮对话上下文管理的基础设施已实现 80%（PromptBuilder 分层注入、摘要异步生成、增量更新、PG 持久化），但关键参数未达到设计目标（`context_window=10` 轮 vs 实际 3 轮，摘要压缩默认关闭），且缺失压缩比 ≥60% 的保证机制，导致长对话场景下模型仍存在"失忆"问题。

## What Changes

- 将 `CONVERSATION_MAX_ROUNDS` 默认值从 **3** 提升至 **10**，匹配设计要求
- 将 `CONVERSATION_SUMMARY_ENABLED` 默认值从 **false** 改为 **true**，正式启用摘要压缩
- 将 `CONVERSATION_SUMMARY_TRIGGER_ROUNDS` 默认值从 **5** 下调至 **3**，使摘要更早介入
- **新增** 压缩比保证机制：摘要生成后校验 `(输入token - 输出token) / 输入token ≥ 60%`，不达标时自动重试并强化 prompt 指令
- **新增** 压缩比指标日志，输出到 lightrag logger，便于运维监控
- 更新 `.env.example` 中的多轮对话相关配置项及注释

## Capabilities

### New Capabilities

- `conversation-compression-ratio`: 压缩比 ≥60% 保证机制 — 摘要生成后自动计算压缩比，不达标时以更严格指令重试（最多 2 次），并输出结构化日志供运维监控

### Modified Capabilities

- `conversation-context-memory`: 滑动窗口默认轮数从 3→10，近期对话层 token 预算保持 2000
- `conversation-summary-compression`: 摘要功能默认启用（false→true），触发阈值从 5 轮降至 3 轮（6→10 条消息），新增压缩比校验流水线

## Impact

- **配置层**: `.env.example`（更新注释和默认值）、`prompt_builder.py`（Layer 配置）、`agent.py`（max_conv_rounds 读取）
- **核心逻辑**: `agent.py` `_call_summary_llm()` — 新增压缩比计算 + 重试循环
- **日志/监控**: 新增 `[SUMMARY-COMPRESSION]` 结构化日志输出
- **规范文件**: 修改 `conversation-context-memory/spec.md`、`conversation-summary-compression/spec.md`；新增 `conversation-compression-ratio/spec.md`
- **迁移**: 无破坏性变更（仅默认值调整），无需数据库迁移
