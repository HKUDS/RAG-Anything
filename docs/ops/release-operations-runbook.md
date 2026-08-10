# 发布备份、恢复与值班手册

## 标准和边界

首版目标为 RPO 不超过 24 小时、RTO 不超过 2 小时。只有完成隔离恢复演练、校验通过且已记录实际时间时才可宣称达标。

| 资产 | 首版责任 | 处理 |
|---|---|---|
| PostgreSQL | 平台运维 | 全库逻辑 `pg_dump`；覆盖 RBAC、审计、撤销、任务、KB、智能体及 PG RAG 表。 |
| `rag_storage` 和经部署明确声明的 `rag_storage_<kb>` | 应用/平台运维 | 显式归档。`.locks`、PID、日志不属于恢复资产。 |
| `uploads` | 应用/平台运维 | 显式归档，恢复后按元数据引用校验。 |
| `output` 和经部署明确声明的 `output_<kb>` | 应用/平台运维 | 显式归档，恢复后只允许受控媒体解析至此类根。未挂载的 `output_<kb>` 是发布阻断项。 |
| `rag_storage_kb_meta.json` | 派生镜像 | 不作为恢复前置条件；PG 为权威元数据。 |
| 模型目录和目录清单 | 部署 owner | 模型默认外部可再现；仅在许可批准后显式纳入。 |
| Redis | 部署 owner | 每个部署标记为可恢复、可重建或外部托管。 |
| 外部图/向量库 | 外部 owner | 必须给出本地快照、恢复、校验和新鲜度契约；否则只可声明部分恢复。 |

配置模板在 `deploy/release-operations.example.json`。它只能保存路径、分类和 owner，不能保存 DSN、密码、令牌或用户数据。

## 日常备份

1. 确认维护窗口或已批准暂停上传与 worker。若未暂停，记录“校验通过但跨资产一致性未证明”。
2. 使用受保护的 `PGPASSFILE` 设置 `PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSFILE`。不得导出或打印其内容。
3. 运行 `python scripts/ops/release_ops.py backup --config <部署配置> --backup-root <非运行态备份根>`。
4. 运行 `python scripts/ops/release_ops.py verify --bundle <bundle>`；仅成功后才发布备份新鲜度指标。
5. 使用部署 owner 的加密和异地复制 wrapper。复制完成前不得更新“verified”时间；保存至少 35 个每日点、12 个每月点。

备份写入同级私有临时目录，只有 dump、归档、manifest 与 checksum 自校验成功后才原子发布。manifest 只列归档产物和聚合大小，绝不列上传文件名、用户或秘密。

## 故障分级和升级

| 等级 | 影响 | 确认 | 升级 |
|---|---|---:|---|
| P1 | 数据丢失风险、PG 不可用、无有效备份 | 15 分钟 | 值班主管、平台 owner、数据 owner。 |
| P2 | 单项降级、Redis 或外部检索不可用、磁盘紧张 | 30 分钟 | 值班主管和对应 dependency owner。 |
| P3 | 告警缺失、演练记录不完整、非生产问题 | 一个工作日 | 运维负责人。 |

先记录告警时间、影响范围、当前备份 ID 和操作者。不得将 DSN、用户数据、错误全文或截图中的密钥写入工单。P1 在恢复决定前必须获得数据 owner 批准。

## 隔离恢复

1. 使用网络和凭据均与生产隔离的 PostgreSQL 实例；数据库名相同不足以保证隔离。
2. 在空的、部署 allowlist 内的隔离根目录执行 verify。确认 manifest 的 `backup_id`。
3. 运行 `python scripts/ops/release_ops.py restore --bundle <bundle> --isolated-root <empty-root> --confirm-backup-id <backup-id> --isolated-pg-database <drill-db> --production-pg-database <prod-name>`。
4. 脚本会拒绝非空目标、错误确认、校验失败、异常归档成员和生产数据库名。不得对生产目录或生产数据库运行 restore。
5. 从隔离数据库导出仅含聚合计数与脱敏引用状态的 inventory，再运行 `validate`。校验角色、审计/撤销表、KB workspace、上传和受控媒体引用。

RTO 从开始隔离恢复到语义验证成功的时间点计算。RPO 是数据时间点与恢复开始时间的差。任一引用、角色、审计或异地副本失败均为演练失败。

## 探针和告警

当前 `/api/health` 与 `/metrics` 保持不变，不能作为发布级 live/readiness 契约。交由共享入口 owner 的接口建议：

- `GET /api/live`: 仅进程/事件循环，200。
- `GET /api/ready`: PG、必需 workspace、schema 兼容与持久任务恢复；失败为 503。
- `GET /api/health`: 可选外部依赖失败为 200/degraded，必需依赖失败为 503，响应不得包含异常原文或秘密。

`deploy/prometheus/release-operations-alerts.yml` 只启用有已证实来源的应用、PG、Redis、磁盘和备份新鲜度告警。上传队列、SSE 错误率、证书到期为接入缺口：

| 指标 | owner | 验收 |
|---|---|---|
| `rag_upload_queue_oldest_seconds` | 应用/PG exporter owner | 持续积压时可查询。 |
| `rag_sse_stream_events_total{outcome}` | 应用 owner | `error/(done+error)` 排除客户端取消。 |
| x509/blackbox 证书指标 | 边缘/证书 owner | 到期前 30 天可告警。 |

## 演练记录

在受控演练证据库使用以下字段，不记录用户数据：

```text
backup_id:
bundle_verified_at_utc:
offsite_copy_verified_at_utc:
restore_started_at_utc:
semantic_validation_completed_at_utc:
observed_rpo:
observed_rto:
result: pass | fail | environment_blocked
consistency_window: proven | not_proven
approval_role:
follow_up_owner:
```

## 部署交接

### Shared health and migration integration

The coordinator-owned integration now exposes `/api/live`, `/api/ready`, and
the sanitized compatibility `/api/health`. Compose starts the one-shot
`migrate` service before `app`; the deployment wrapper must set
`MIGRATION_BACKUP_ACKNOWLEDGED=true` only after backup verification. A real
isolated restore drill remains required before claiming the RPO/RTO target.

- 调度/加密/异地复制及密钥 custody 由平台运维负责。
- `deploy/rag-anything.service` 目前仅允许 `rag_storage` 和 `logs` 写入，未覆盖 `uploads`/`output`；部署 owner 必须在启用运行态或恢复流程前解决该契约。
- Compose 的 `pgdata` 是命名卷，必须使用逻辑 dump，禁止复制运行中的 PG 卷。
- 健康路由、`server.py`、Compose、nginx、迁移和认证核心未被本 change 修改。
