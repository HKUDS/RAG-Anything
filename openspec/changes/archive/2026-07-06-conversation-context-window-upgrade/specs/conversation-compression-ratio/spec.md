# conversation-compression-ratio

## Purpose

确保对话摘要的压缩效果达到可量化标准（压缩比 ≥60%），避免摘要过于冗长而失去压缩意义。通过自动校验和重试机制，保证摘要质量的同时控制 token 开销。

## ADDED Requirements

### Requirement: 压缩比计算

系统 SHALL 在每次生成摘要后，自动计算压缩比：`compression_ratio = 1 - (len(summary) / len(input_transcript))`，其中 `input_transcript` 为传入 LLM 的对话记录文本，`summary` 为 LLM 返回的摘要文本。

#### Scenario: 正常压缩比计算

- **WHEN** `_call_summary_llm()` 成功返回摘要文本
- **THEN** 系统计算 `compression_ratio = 1 - len(summary) / len(input_transcript)`
- **AND** 输出结构化日志：`[SUMMARY-COMPRESSION] input_chars=N, output_chars=M, ratio=X%, pass=true/false`

#### Scenario: 增量摘要的压缩比

- **WHEN** 已有摘要（existing_summary 非空）进行增量更新
- **THEN** `input_transcript` 为"已有摘要 + 新增消息"的合并文本
- **AND** 压缩比计算使用合并后的 `input_transcript` 总长度

### Requirement: 压缩比阈值校验

系统 SHALL 校验压缩比是否达到配置阈值 `CONVERSATION_COMPRESSION_RATIO`（默认 0.60，即 60%）。

#### Scenario: 压缩比达标

- **WHEN** 生成的摘要压缩比 ≥ `CONVERSATION_COMPRESSION_RATIO`（默认 0.60）
- **THEN** 系统接受该摘要，写入 PG 并返回
- **AND** 日志标记 `pass=true`

#### Scenario: 压缩比不达标触发重试

- **WHEN** 生成的摘要压缩比 < `CONVERSATION_COMPRESSION_RATIO`
- **AND** 重试次数未达上限 `CONVERSATION_COMPRESSION_MAX_RETRIES`（默认 2）
- **THEN** 系统重试 LLM 调用，prompt 追加压缩强度指令
- **AND** 日志记录当前重试次数和不达标的压缩比值

### Requirement: 重试强化策略

系统 SHALL 在每次重试时逐步强化 prompt 中的压缩强度要求。

#### Scenario: 第 1 次重试

- **WHEN** 首次生成的摘要压缩比不达标
- **THEN** prompt 追加：`"请大幅压缩摘要，目标是将原始对话压缩至 40% 以下长度。只保留最关键的事实和结论。"`

#### Scenario: 第 2 次重试

- **WHEN** 第 1 次重试后压缩比仍不达标
- **THEN** prompt 追加：`"极限压缩模式：每条信息不超过 10 个字，只输出核心结论。"`

#### Scenario: 重试耗尽后优雅降级

- **WHEN** 所有重试（默认 2 次）后压缩比仍不达标
- **THEN** 系统记录警告日志：`[SUMMARY-COMPRESSION] All retries exhausted. Best ratio: X%, accepting degraded result.`
- **AND** 使用最后一次生成的摘要（不阻塞用户请求）
- **AND** 将摘要写入 PG（后续增量更新时可改进）

### Requirement: 压缩比配置

系统 SHALL 通过环境变量控制压缩比行为。

#### Scenario: 环境变量

- **WHEN** 系统启动
- **THEN** 读取以下环境变量：
  - `CONVERSATION_COMPRESSION_RATIO`：目标压缩比，默认 `0.60`（60%）
  - `CONVERSATION_COMPRESSION_MAX_RETRIES`：最大重试次数，默认 `2`

#### Scenario: 默认值

- **WHEN** 上述环境变量未设置
- **THEN** 使用默认值：`CONVERSATION_COMPRESSION_RATIO=0.60`，`CONVERSATION_COMPRESSION_MAX_RETRIES=2`

### Requirement: 压缩比非阻塞

系统 SHALL 确保压缩比校验和重试不影响用户交互。

#### Scenario: 校验不阻塞用户响应

- **WHEN** 压缩比校验和重试发生在 `_maybe_generate_summary()` 中
- **THEN** 整个过程在用户收到响应后异步执行（继承现有 fire-and-forget 模式）
- **AND** 用户的当前查询和下一条查询均不等待校验完成

#### Scenario: 摘要未就绪时的降级

- **WHEN** 压缩比重试尚未完成
- **AND** 用户发送下一条查询
- **THEN** 系统使用已有的 `summary`（或 NULL），不等待重试完成
- **AND** PromptBuilder 行为与规范 `conversation-summary-compression` 一致
