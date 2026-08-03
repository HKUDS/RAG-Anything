## Context

智能体标准路径和 agentic 路径都在文本检索后调用 `recall_query_images`，随后通过 `_controlled_recalled_media` 将后端路径转换为无路径的受控 payload。当前两阶段继续使用请求开始时创建的 `retrieval_deadline`；当 graph 通道接近 8 秒截止时，媒体阶段即使已经发现 3 张图片，也会在 grant/证据校验期间超时并由调用方整体清空。

会话摘要通过 `pg_get_summary`、`pg_update_summary` 和 `pg_get_summary_updated_at` 使用两个摘要列。历史迁移 `009_conversation_summary.sql` 定义了这些列，但 `scripts/pg_setup.py` 的显式清单只执行另一个 `009_uploaded_files_meta.sql`，当前数据库实测两列均不存在。

## Goals / Non-Goals

**Goals:**
- 标准、CoT 和 ReAct 路径的媒体召回从媒体阶段开始获得独立、可配置的 8 秒预算。
- 媒体超时时保留已经完成全部受控校验的图片，未验证路径不得进入 SSE。
- 通过新的幂等迁移修复历史数据库并确保新初始化链包含该迁移。
- 对当前本地 PostgreSQL 执行迁移并完成真实摘要持久化验收。

**Non-Goals:**
- 不调整 RRF graph 通道超时、检索排序或 LLM 生成时限。
- 不修改 3 张图片上限、受控根、grant、sha256 或 KB 所有权证据链。
- 不修改前端、HTTP/SSE 字段、摘要触发阈值或压缩算法。
- 不重命名或删除历史 `009_conversation_summary.sql`。

## Decisions

### 决策 1：媒体阶段使用独立 deadline

新增 `AGENT_MEDIA_RECALL_TIMEOUT`，默认 8 秒且最小 0.1 秒。非法数字、NaN 或无穷值回退到默认值。每次进入媒体阶段时以当前 monotonic time 重新计算 deadline，而不是复用 `retrieval_deadline`。标准与 agentic 路径调用同一私有辅助函数，避免再次漂移。备选方案“扩大整个检索预算”被否决，因为 graph 仍可占满新增预算且继续挤压媒体。

### 决策 2：只保留已受控验证的部分结果

辅助函数先在媒体 deadline 内完成路径召回，再逐张执行 `resolve_controlled_media_payload`。每张校验都受同一媒体 deadline 约束；截止时由辅助函数内部返回此前已生成的 payload 和 `timed_out=True`，不得在整个辅助函数外层使用会丢失局部结果的统一超时取消。原始路径、尚未完成 grant/证据校验的候选和失败 payload 一律不返回。调用方据此记录 `media outcome=timeout` 和 `timeout-partial`/`timeout-empty` 结构化日志，但不清空已验证图片。请求 `CancelledError` 始终向上传播，且超时后不得保留继续签发 grant 的后台任务。

### 决策 3：新增 027 补迁移

新增 `027_agent_conversation_summary_columns.sql`，以 `ADD COLUMN IF NOT EXISTS` 和 `CREATE INDEX IF NOT EXISTS` 补齐两列与部分索引。保留旧 009 作为历史记录；使用新编号保证按增量部署的既有环境也能发现修复。迁移仅新增可空列和索引，不回填或修改会话数据。

### 决策 4：显式补齐初始化清单尾部

`pg_setup.py` 继续使用显式清单，不在本次改为自动扫描；追加现有 024、025、026 和新增 027，避免改变早期重复编号迁移的选择语义。024 为 COMMENT、025 为已批准的邮箱列移除、026 为触发器移除，均使用可重复执行的 DDL；它们只进入新初始化/完整迁移入口，本轮当前数据库验收仅单独执行 027。增加清单顺序契约测试防止后续迁移再次遗漏。

## Risks / Trade-offs

- [媒体阶段最多增加 8 秒延迟] → 仅在受控媒体解析实际阻塞时发生，默认值可由环境变量下调；文本检索与 LLM 契约不变。
- [部分结果返回可能少于 3 张] → 优先保证已验证图片可用和安全，不等待慢候选导致全部丢失。
- [ALTER TABLE 获取短暂锁] → 仅新增可空列与索引，在本地验收窗口执行；迁移幂等可重试。
- [旧 009 与新 027 DDL 重复] → 全部使用 IF NOT EXISTS，保留历史兼容且不会重复数据变更。

## Migration Plan

1. 部署代码和 `027` 前，只读查询当前列与索引状态。
2. 在当前本地 PostgreSQL 连续执行两次 `027`；再次查询确认两列及 `summary_updated_at WHERE summary IS NOT NULL` 部分索引存在。
3. 通过摘要仓库完成写入、读取与更新时间读取闭环，再重启后端触发真实摘要并确认无 undefined-column 告警。
4. 不在当前数据库运行完整 `pg_setup.py`，避免重放与本任务无关的历史迁移；回滚代码时保留新增列与索引，不执行破坏性 down migration。

## Open Questions

无阻塞项。
