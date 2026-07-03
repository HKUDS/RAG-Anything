## MODIFIED Requirements

### Requirement: 对话历史注入 LLM Prompt

系统 SHALL 通过 `PromptBuilder` 统一管线将对话历史注入 LLM prompt，支持分层注入（摘要 + 近期对话），使模型能理解上下文延续性。

#### Scenario: 指代消解 — 代词替换
- **WHEN** 会话中已有 "用户: PLC故障码E001是什么意思？→ 助手: E001表示电机过载..." 
- **AND** 用户新提问 "这个故障怎么解决？"
- **THEN** LLM prompt 中包含对话历史上下文（摘要层或近期消息层）
- **AND** LLM 能理解"这个"指代 E001 电机过载，并基于检索文档给出解决方案

#### Scenario: 无会话时的单轮行为
- **WHEN** 用户查询未携带 `thread_id`
- **THEN** PromptBuilder 不注入对话历史相关层
- **AND** 行为与当前单轮查询完全一致（向后兼容）

#### Scenario: Prompt 分层结构
- **WHEN** 查询带有有效 `thread_id` 且历史非空
- **THEN** LLM prompt 按优先级分层组装：系统指令 →（用户画像，如有）→（对话摘要，如有）→ 图片上下文 → 近期对话 → 检索文档 → 当前问题 → 引用指令
- **AND** 各区之间有明确分隔标记
- **AND** 若同时有摘要和近期对话，两者分别作为独立层注入

### Requirement: 历史轮数和 Token 预算控制

系统 SHALL 通过环境变量控制注入 prompt 的历史轮数、token 上限，以及新增的摘要相关配置。

#### Scenario: 历史轮数限制
- **WHEN** 会话有 10 轮对话历史
- **AND** `CONVERSATION_MAX_ROUNDS` 设为 3
- **THEN** 仅最近 3 轮未包含在摘要中的消息注入近期对话层

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
- **THEN** 系统使用默认值：`CONVERSATION_MAX_ROUNDS=3`，`CONVERSATION_MAX_TOKENS=2000`，`CONVERSATION_SUMMARY_MAX_TOKENS=1000`

### Requirement: 持久化存储

系统 SHALL 将会话数据和摘要持久化到 PostgreSQL，服务器重启后数据不丢失。

#### Scenario: 消息持久化写入
- **WHEN** 新消息添加到会话
- **THEN** 系统通过 `pg_add_message()` 写入 `agent_messages` 表
- **AND** 用户下次查询时可读取完整历史

#### Scenario: 摘要持久化写入
- **WHEN** 摘要生成完成
- **THEN** 系统更新 `agent_conversations` 表的 `summary` 和 `summary_updated_at` 字段
- **AND** 摘要数据在服务器重启后保持可用

#### Scenario: 启动时验证
- **WHEN** RAG-Anything 服务启动
- **THEN** `pg_ensure_agent_tables()` 验证 `agents`、`agent_conversations`、`agent_messages` 表存在
- **AND** 若表不存在则输出警告，回退到 JSON 文件存储
