## Context

当前多轮对话上下文的代码基础设施（PromptBuilder 分层注入、摘要异步生成、增量更新、PG 持久化）已通过 2026-07-02 的 `enhance-conversation-memory` 变更完整实现。但实际运行参数仍停留在早期开发阶段（`CONVERSATION_MAX_ROUNDS=3`、摘要默认关闭），且缺失压缩比质量保障。

本设计聚焦于"达标调优"——不改架构，只完成三件事：(1) 调整默认参数至设计目标值，(2) 启用摘要压缩，(3) 新增压缩比校验循环。

## Goals / Non-Goals

**Goals:**
- `CONVERSATION_MAX_ROUNDS` 默认值 3→10，匹配 `context_window=10` 设计目标
- `CONVERSATION_SUMMARY_ENABLED` 默认值 false→true，正式启用摘要压缩
- `CONVERSATION_SUMMARY_TRIGGER_ROUNDS` 默认值 5→3，让摘要更早介入长对话
- 新增压缩比校验：`_call_summary_llm()` 生成摘要后自动计算 `(输入token - 输出token) / 输入token`，不达标（<60%）时以强化 prompt 重试
- 新增环境变量 `CONVERSATION_COMPRESSION_RATIO`（默认 0.60）和 `CONVERSATION_COMPRESSION_MAX_RETRIES`（默认 2）
- 输出结构化日志 `[SUMMARY-COMPRESSION]` 记录每次摘要的输入/输出 token 及压缩比

**Non-Goals:**
- 不改动 PromptBuilder 架构（分层模型已完善）
- 不改动数据库 schema（migration 009 的 `summary` / `summary_updated_at` 字段已就绪）
- 不引入精确 tokenizer（继续使用 `len(text)//2` 启发式估算）
- 不改变 API 契约或消息存储格式
- 不做向量化记忆或语义记忆

## Decisions

### Decision 1: 压缩比校验位置 — 嵌入 `_call_summary_llm()` 内部

**选择**：在 `_call_summary_llm()` 内部添加压缩比计算和重试循环，而非在外部包装。

**理由**：
- `_call_summary_llm()` 已持有完整的输入消息列表和输出摘要文本，所有数据都在手边
- 重试逻辑与 LLM 调用紧密耦合（每次重试需要修改 prompt），放在内部更内聚
- 调用方 `_maybe_generate_summary()` 无需感知重试细节，接口不变

**替代方案**：在 `_maybe_generate_summary()` 中包装重试 → 拒绝，因为需要把 prompt 构造逻辑暴露到调用方，破坏封装。

### Decision 2: 压缩比计算公式 — 简单字符数比

**选择**：`compression_ratio = 1 - (len(summary) / len(input_transcript))`，使用字符数而非 token 估算。

**理由**：
- 输入和输出使用相同度量（字符数），比值与 token 比值近似
- 避免 token 估算误差在比值计算中被放大
- 简单、无需外部依赖

**阈值**：`compression_ratio < CONVERSATION_COMPRESSION_RATIO`（默认 0.60）时触发重试。

### Decision 3: 重试策略 — 强化 prompt 指令，最多 2 次

**选择**：每次重试在 prompt 中追加压缩强度要求，而非更换模型或调整 temperature。

**理由**：
- 同一模型通常能通过更明确的指令达到更高压缩比
- 换模型增加复杂度和不确定性
- 2 次重试上限防止无限循环消耗 token

**重试 prompt 强化策略**：
```
第 1 次重试：追加 "请大幅压缩摘要，目标是将原始对话压缩至 40% 以下长度。只保留最关键的事实和结论。"
第 2 次重试：追加 "极限压缩模式：每条信息不超过 10 个字，只输出核心结论。"
```

**妥协接受**：2 次重试后仍不达标 → 记录警告日志，使用最后一次结果（优雅降级，不阻塞用户）。

### Decision 4: `CONVERSATION_MAX_ROUNDS` 10 轮 + token_budget=2000 的关系

**选择**：保持双层截断机制——先按轮数截取最近 20 条消息（10轮×2），再按 token 预算从旧到新截断。

**理由**：
- 轮数是"软上限"（决定最多取多少条消息来考虑），token 预算是"硬上限"（最终注入 prompt 的字符量）
- 大部分短消息场景下 10 轮可以完整装入 2000 token 预算
- 长消息场景下 token 预算自动兜底，防止撑爆 prompt
- 此设计无需代码改动 —— 只改默认值即可生效

### Decision 5: `CONVERSATION_SUMMARY_TRIGGER_ROUNDS` 5→3

**选择**：将触发阈值从 5 轮（10 条消息）降至 3 轮（6 条消息）。

**理由**：
- 配合 context_window=10，摘要应在滑动窗口前半段（前 3 轮）即开始压缩
- 3 轮后触发摘要意味着：当对话达到 10 轮时，早期 7 轮已被压缩为摘要 + 最近 3 轮原始消息 = 两层覆盖完整 10 轮历史
- 更早介入 = 更早释放 token 预算给近期对话和检索内容

## Risks / Trade-offs

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 摘要功能默认启用后 LLM 调用次数增加 | 高 | API 费用上升 ~每 3 轮 1 次摘要调用 | 摘要调用使用 `max_tokens=500`（小），且是异步非阻塞；费用增幅可控 |
| 压缩比重试导致摘要生成延迟 | 低 | 用户下次查询时摘要可能未就绪 | 不阻塞用户响应；查询时降级为纯截断 |
| `CONVERSATION_MAX_ROUNDS=10` 导致 prompt 变长 | 中 | 部分消息可能撑爆 token 预算 | Token 预算硬截断兜底；PromptBuilder 全局预算（MAX_TOKENS=8192）提供二次保护 |
| 压缩比用字符数估算不够精确 | 低 | 中英文混合场景下字符/token 比不同 | 作为相对度量足够；不要求绝对精确 |
| 更频繁的摘要触发（3 轮 vs 5 轮）可能产生低质量摘要 | 低 | 短对话摘要内容少 | 摘要 prompt 要求 2-5 句话，短对话自然生成短摘要 |

## Migration Plan

1. **部署步骤**：
   - 更新代码（修改默认值 + 新增压缩比逻辑）
   - 重启服务（无需数据库迁移）
   - 已有会话的摘要会在下次消息达到触发阈值时自动生成

2. **回滚**：
   - 设置 `CONVERSATION_SUMMARY_ENABLED=false` 关闭摘要（回退到纯截断）
   - 设置 `CONVERSATION_MAX_ROUNDS=3` 恢复旧行为
   - 无需数据回滚

3. **兼容性**：
   - 无破坏性变更
   - 已有 `.env` 中的显式配置优先级高于新的默认值
   - 数据库 schema 无变化

## Open Questions

无 — 所有设计决策已在本文件中确认。
