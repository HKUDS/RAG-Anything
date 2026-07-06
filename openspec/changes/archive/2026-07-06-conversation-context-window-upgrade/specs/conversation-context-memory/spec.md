# conversation-context-memory (Delta)

## MODIFIED Requirements

### Requirement: 历史轮数和 Token 预算控制

系统 SHALL 通过环境变量控制注入 prompt 的历史轮数、token 上限，以及新增的摘要相关配置。

#### Scenario: 历史轮数限制

- **WHEN** 会话有 20 轮对话历史
- **AND** `CONVERSATION_MAX_ROUNDS` 设为 10
- **THEN** 仅最近 10 轮未包含在摘要中的消息注入近期对话层

#### Scenario: Token 预算限制

- **WHEN** 近期对话层文本估算超过 `CONVERSATION_MAX_TOKENS`（默认 2000）
- **THEN** 系统从最旧的消息开始截断，直到总 token 数不超过上限

#### Scenario: 分层 Token 预算分配

- **WHEN** 多个上下文层同时启用
- **THEN** 每层消耗各自的 `max_tokens` 配额
- **AND** 总 token 超全局预算时，按 priority 从低到高截断各层

#### Scenario: 摘要层 Token 预算

- **WHEN** 对话摘要层启用
- **AND** 摘要文本超过 `CONVERSATION_SUMMARY_MAX_TOKENS`（默认 1000）
- **THEN** 摘要文本从开头截断至预算内

#### Scenario: 环境变量默认值

- **WHEN** 上述环境变量未设置
- **THEN** 系统使用默认值：`CONVERSATION_MAX_ROUNDS=10`，`CONVERSATION_MAX_TOKENS=2000`，`CONVERSATION_SUMMARY_MAX_TOKENS=1000`
