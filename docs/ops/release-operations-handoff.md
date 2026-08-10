# 发布运维交接

## Coordinator Integration Update (2026-08-04)

The coordinator has implemented the shared health contract: `/api/live` is a
dependency-free 200 probe, `/api/ready` returns 503 for required dependency
failure, and `/api/health` is sanitized and status-code compatible. Compose now
gates the app on a one-shot migration service and requires explicit database
secrets plus a deployment-injected backup acknowledgement. The remaining
release gap is Docker/TLS-backed staging evidence.

## Drill Evidence (2026-08-04)

A real PostgreSQL 16.3 isolated recovery drill completed with disposable source
and destination databases plus a temporary file asset root. The sequence was
`backup`, `verify`, `restore`, and `validate`; both a database marker and the
archived asset were verified after restore. The temporary databases and root
were then removed. Docker/Compose, TLS certificate, and staging deployment
evidence remain unavailable in this workspace.

## 需要部署接入

- `PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSFILE`：只由备份/演练服务身份提供。
- 加密 recipient/key reference、异地目的地和保留策略：仅部署秘密管理系统配置。
- Prometheus exporter：应用 `/metrics` 路径由 `METRICS_PATH` 和 `ENABLE_METRICS` 决定；PG、Redis、主机和证书由各自 exporter owner 接入。
- 外部 Redis、图/向量库、模型目录：填写 inventory 分类、owner 和本地恢复契约。

## 共享入口请求

已由协调者实施 `/api/live`、`/api/ready` 和脱敏的 `/api/health`。验收仍要求：PG 失败时 live 为 200、ready 为 503；三个响应均无 DSN、主机、用户名或异常原文。

## 回滚

禁用系统 timer 和 Alertmanager 路由，撤销备份服务身份；已完成的加密恢复点按数据保留策略处理。脚本不更改生产数据。

## 总结增量（供唯一协调者合并）

新增 release-operations 工具、告警示例和中文 runbook，定义了未实测的 RPO <=24h/RTO <=2h 标准。真实隔离 PG 演练、异地加密副本、外部存储责任确认、`output_<kb>` 持久挂载与共享健康接口仍是发布阻断项；不得称为已达标。
