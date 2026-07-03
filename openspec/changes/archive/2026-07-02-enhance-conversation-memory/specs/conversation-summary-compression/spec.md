## ADDED Requirements

### Requirement: 摘要触发条件

系统 SHALL 在对话消息数超过配置阈值时，触发生成对话摘要。

#### Scenario: 首次触发生成摘要
- **WHEN** 智能体会话的消息数首次超过 `CONVERSATION_SUMMARY_TRIGGER_ROUNDS * 2` 条（默认 10 条，即 5 轮）
- **AND** `CONVERSATION_SUMMARY_ENABLED=true`
- **THEN** 系统在本次响应完成后，异步调用 LLM 将早期消息压缩为摘要
- **AND** 摘要文本存储到 `agent_conversations.summary` 字段
- **AND** `summary_updated_at` 更新为当前时间

#### Scenario: 未达阈值时不生成
- **WHEN** 会话消息数未超过 `CONVERSATION_SUMMARY_TRIGGER_ROUNDS * 2` 条
- **THEN** 系统不触发摘要生成
- **AND** `agent_conversations.summary` 保持 NULL（若之前未生成）

#### Scenario: 功能关闭时跳过
- **WHEN** `CONVERSATION_SUMMARY_ENABLED=false`
- **THEN** 即使消息数超阈值，也不触发摘要生成
- **AND** 系统回退到当前纯截断行为

### Requirement: 增量摘要更新

系统 SHALL 在已有摘要的基础上，对新增消息进行增量摘要更新，而非每次全量重新生成。

#### Scenario: 增量摘要
- **WHEN** `agent_conversations.summary` 已有值（非 NULL）
- **AND** 新增消息数再次达到触发阈值
- **THEN** 系统将"已有摘要文本 + 新增消息"发送给 LLM，要求合并生成新摘要
- **AND** 更新 `agent_conversations.summary` 和 `summary_updated_at`

#### Scenario: 增量摘要的 LLM Prompt
- **WHEN** 执行增量摘要
- **THEN** LLM 摘要 Prompt 包含：
  - 已有摘要文本
  - 最近未摘要的新增消息（自 `summary_updated_at` 之后的消息）
  - 指令："将以下新增内容融入已有摘要，生成更新后的摘要。保持 2-5 句话，只总结事实，不添加新信息。"

### Requirement: 摘要注入 Prompt

系统 SHALL 在构建 Prompt 时，若存在摘要，将摘要作为独立的上下文层注入。

#### Scenario: 摘要 + 近期消息双注入
- **WHEN** 会话有已生成的摘要（`summary` 非 NULL）
- **AND** 每次查询时
- **THEN** Prompt 包含两层：
  - 摘要层：`## 对话摘要\n{summary text}`（priority=20，最多 1000 token）
  - 近期消息层：最近 `CONVERSATION_MAX_ROUNDS` 轮未包含在摘要中的消息（priority=30）

#### Scenario: 无摘要时降级为纯截断
- **WHEN** 会话无摘要（`summary` 为 NULL）
- **THEN** 对话历史注入行为与当前一致——纯截断最近 N 轮消息

### Requirement: 摘要异步与非阻塞

系统 SHALL 异步生成摘要，不影响用户交互的响应速度。

#### Scenario: 摘要不阻塞用户响应
- **WHEN** 触发摘要生成条件
- **THEN** 摘要生成在用户收到本次响应之后、后台异步执行
- **AND** 用户的下一条查询不等待摘要完成（使用已有的 `summary` 或 NULL）

#### Scenario: 摘要生成失败时优雅降级
- **WHEN** LLM 摘要调用失败（网络异常、API 错误、超时等）
- **THEN** 系统记录警告日志，不更新 `summary` 字段
- **AND** 用户查询不受影响，使用当前截断逻辑继续
- **AND** 下次触发条件满足时重试

### Requirement: 摘要相关配置

系统 SHALL 通过环境变量控制摘要功能的行为。

#### Scenario: 环境变量列表
- **WHEN** 系统启动
- **THEN** 读取以下环境变量：
  - `CONVERSATION_SUMMARY_ENABLED`：是否启用摘要功能，默认 `false`
  - `CONVERSATION_SUMMARY_TRIGGER_ROUNDS`：触发摘要的最小对话轮数，默认 `5`
  - `CONVERSATION_SUMMARY_MAX_TOKENS`：用于摘要 Prompt 注入的最大 token 数，默认 `1000`
  - `CONVERSATION_SUMMARY_LLM_MODEL`：用于摘要生成的 LLM 模型，默认为主模型

#### Scenario: 默认值
- **WHEN** 上述环境变量未设置
- **THEN** 使用默认值，摘要功能处于关闭状态（向后兼容）
