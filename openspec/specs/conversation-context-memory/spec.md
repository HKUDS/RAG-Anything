## ADDED Requirements

### Requirement: 会话生命周期管理

系统 SHALL 支持会话（thread）的创建、列出、删除操作。每个会话归属于一个用户，包含唯一 ID、标题和消息列表。

#### Scenario: 创建新会话
- **WHEN** 用户发送 `POST /api/conversations` 请求，携带 `title: "PLC故障诊断"`
- **THEN** 系统创建一个新 thread，返回 `thread_id` 和 `title`
- **AND** 该会话的 `created_at` 和 `updated_at` 设为当前时间

#### Scenario: 列出用户会话
- **WHEN** 用户发送 `GET /api/conversations` 请求
- **THEN** 系统返回该用户所有会话摘要（id、title、消息数、更新时间），按更新时间倒序

#### Scenario: 删除会话
- **WHEN** 用户发送 `DELETE /api/conversations/{thread_id}` 请求
- **THEN** 系统删除该会话及其所有消息
- **AND** 若会话不存在返回 404

#### Scenario: 查询时自动创建会话
- **WHEN** 用户发送 `POST /api/query` 请求，携带 `thread_id: ""`（空字符串）
- **AND** 会话不存在
- **THEN** 系统自动创建新会话，标题取 query 的前 50 个字符
- **AND** 系统的响应中包含 `thread_id` 字段

### Requirement: 会话用户隔离

系统 SHALL 确保每个用户只能访问自己创建的会话。

#### Scenario: 跨用户访问被拒绝
- **WHEN** 用户 A 尝试通过 `GET /api/conversations` 或 `DELETE /api/conversations/{thread_id}` 操作用户 B 的会话
- **THEN** 系统返回空列表（GET）或 404（DELETE），不暴露其他用户数据

### Requirement: 对话历史注入 LLM Prompt

系统 SHALL 在生成回答时，将当前会话的最近 N 轮对话历史注入 LLM prompt，使模型能理解上下文延续性。

#### Scenario: 指代消解 — 代词替换
- **WHEN** 会话中已有 "用户: PLC故障码E001是什么意思？→ 助手: E001表示电机过载..." 
- **AND** 用户新提问 "这个故障怎么解决？"
- **THEN** LLM prompt 中包含对话历史上下文
- **AND** LLM 能理解"这个"指代 E001 电机过载，并基于检索文档给出解决方案

#### Scenario: 无会话时的单轮行为
- **WHEN** 用户查询未携带 `thread_id`
- **THEN** LLM prompt 中不包含对话历史区
- **AND** 行为与当前单轮查询完全一致（向后兼容）

#### Scenario: Prompt 结构
- **WHEN** 查询带有有效 `thread_id` 且历史非空
- **THEN** LLM prompt 结构为：对话历史区 → 检索文档区 → 当前问题 → 回答指令
- **AND** 各区之间有明确分隔标记

### Requirement: 查询改写接入历史上下文

系统 SHALL 在启用查询改写（`ENABLE_QUERY_REWRITE=true`）时，将对话历史传入 `rewrite_query()` 以辅助指代消解。

#### Scenario: 基于历史的查询改写
- **WHEN** 会话中有前一轮对话上下文
- **AND** 用户提问 "它有哪些常见原因？"
- **THEN** `rewrite_query()` 接收到最近 3 轮对话历史
- **AND** 输出改写后的查询如 "PLC故障码E001的常见原因"

#### Scenario: 查询改写失败时回退
- **WHEN** `rewrite_query()` 调用失败（网络异常、API 错误等）
- **THEN** 系统使用原始查询继续检索，不影响主流程

### Requirement: 历史轮数和 Token 预算控制

系统 SHALL 通过环境变量控制注入 prompt 的历史轮数和 token 上限。

#### Scenario: 历史轮数限制
- **WHEN** 会话有 10 轮对话历史
- **AND** `CONVERSATION_MAX_ROUNDS` 设为 3
- **THEN** 仅最近 3 轮注入 LLM prompt

#### Scenario: Token 预算限制
- **WHEN** 最近 3 轮历史文本估算超过 `CONVERSATION_MAX_TOKENS`（默认 2000）
- **THEN** 系统从最旧的消息开始截断，直到总 token 数不超过上限

#### Scenario: 环境变量默认值
- **WHEN** `CONVERSATION_MAX_ROUNDS` 或 `CONVERSATION_MAX_TOKENS` 未设置
- **THEN** 系统使用默认值：`CONVERSATION_MAX_ROUNDS=3`，`CONVERSATION_MAX_TOKENS=2000`

### Requirement: 持久化存储

系统 SHALL 将会话数据持久化到 `conversations.json` 文件，服务器重启后数据不丢失。

#### Scenario: 持久化写入
- **WHEN** 新消息添加到会话
- **THEN** 系统在回答生成完成后异步写入 `conversations.json`
- **AND** 用户下次查询时可读取完整历史

#### Scenario: 启动时加载
- **WHEN** RAG-Anything 服务启动
- **THEN** `ConversationManager` 自动加载 `conversations.json`
- **AND** 若文件不存在则创建空文件

### Requirement: 会话数量限制

系统 SHALL 限制每用户最大活跃会话数，防止资源滥用。

#### Scenario: 超过上限时拒绝创建
- **WHEN** 用户已有 50 个会话
- **AND** 尝试创建新会话
- **THEN** 系统返回 400 错误，提示 "已达到最大会话数限制（50）"

#### Scenario: 删除后可以创建
- **WHEN** 用户有 50 个会话
- **AND** 删除 1 个会话后尝试创建新会话
- **THEN** 系统允许创建
