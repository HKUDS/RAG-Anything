## Why

智能体问答的图片召回与文本检索共用 8 秒截止时间，图谱通道耗尽预算后会清空已经发现的引用图片；同时，会话摘要代码依赖 `agent_conversations.summary` 与 `summary_updated_at`，但项目初始化迁移清单漏掉历史摘要迁移，导致摘要生成成功后无法持久化并反复消耗模型调用。

## What Changes

- 为标准、CoT 和 ReAct 智能体路径提供独立的 8 秒媒体召回预算，通过新的 `AGENT_MEDIA_RECALL_TIMEOUT` 环境变量配置。
- 统一图片召回与受控 payload 转换；媒体预算耗尽时保留已完成受控校验的图片，仍拒绝未验证路径并保持最多 3 张。
- 新增幂等迁移 `027_agent_conversation_summary_columns.sql`，补齐摘要列与索引，兼容已经跳过旧 `009_conversation_summary.sql` 的数据库。
- 更新 PostgreSQL 初始化迁移清单，补入 `024` 至 `027`；对当前本地数据库执行新增迁移并验证摘要写读闭环。
- 增加媒体 deadline、部分结果保留、迁移幂等和迁移清单回归测试。

## Capabilities

### New Capabilities

<!-- 无新能力 -->

### Modified Capabilities

- `query-endpoint-image-discovery`: 智能体图片召回必须使用独立媒体预算，并在超时时保留已完成安全校验的图片。
- `conversation-summary-compression`: 摘要所需数据库列必须通过当前迁移链可靠创建，使异步摘要可持久化。

## Impact

- 后端：智能体媒体召回编排与超时配置。
- 数据库：新增两个可空列和一个部分索引；不删除或改写现有会话数据。
- 运维：PostgreSQL 初始化清单增加 `024` 至 `027`，当前本地数据库执行 `027`。
- 测试与文档：新增定向测试、环境变量示例、OpenSpec delta specs 和项目总结记录。
- 无前端、HTTP/SSE 数据结构、依赖或 RBAC 变更。
