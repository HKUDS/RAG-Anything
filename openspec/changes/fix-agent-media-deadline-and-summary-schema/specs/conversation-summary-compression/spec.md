## ADDED Requirements

### Requirement: 会话摘要 Schema 通过当前迁移链可用

系统 SHALL 通过当前 PostgreSQL 迁移链幂等创建 `agent_conversations.summary`、`summary_updated_at` 及摘要更新时间索引，使已有部署和全新初始化均可持久化会话摘要。

#### Scenario: 历史数据库缺少摘要列
- **WHEN** 数据库已有 `agent_conversations` 表但缺少一个或两个摘要列
- **THEN** 新增迁移 MUST 补齐缺失列和索引
- **AND** MUST NOT 删除、覆盖或回填现有会话数据

#### Scenario: 重复执行摘要迁移
- **WHEN** 摘要列和索引已经存在
- **THEN** 重复执行迁移 MUST 成功
- **AND** 现有摘要与会话数据 MUST 保持不变

#### Scenario: 摘要生成后成功持久化
- **WHEN** 摘要压缩校验通过并调用摘要仓库写入
- **THEN** 系统 MUST 更新 `summary` 与 `summary_updated_at`
- **AND** 后续读取 MUST 返回已持久化摘要
- **AND** 日志 MUST NOT 出现摘要列不存在的告警
