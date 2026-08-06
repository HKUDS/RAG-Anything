## Why

存量知识库（视频、odl解析、新能源、odl图片修复2.0/4.0、odl解析_图片修复、测试共 7 个 workspace）的向量仍全部写入旧的无后缀表（`lightrag_vdb_chunks/entity/relation`）。部署 embedding 身份守卫后，`create_rag` 在 LightRAG 初始化前以 `embedding_legacy_storage_incompatible` fail-closed 拦截，导致这些 KB 的查询在 `query_core_acquire` 阶段 28ms 内失败且无日志 traceback，文档列表降级为只读摘要。按用户决定：不保留旧向量，清空 legacy 向量并注册身份，使存量 KB 恢复初始化；未来上传全部写入带 identity 后缀的新表。本变更承接 `stabilize-lightrag-embedding-kb-isolation` 中“存量 legacy 数据显式迁移留待后续”的开放问题。

## What Changes

- 新增一次性运维脚本 `scripts/purge_legacy_embedding_vectors.py`：
  - `--dry-run`（默认）：大小写不敏感发现 legacy 向量表与全部 suffixed 向量表（含 `workspace` 列），动态枚举含数据的 workspace，按表×workspace 输出行数基线，并输出 suffixed 孤儿行清单。
  - `--apply`：必须提供 `--backup-dir` 并通过备份门禁（每张实际存在的 legacy 表有非空且含 COPY 的 dump 文件）；单事务内取 workspace advisory lock，以 `./rag_storage` 为权威身份并交叉校验运行时 env，逐 workspace `FOR UPDATE` 冲突校验后写入注册（INSERTED/EXISTED），删除该 workspace 在 3 张 legacy 表中的全部行，逐表校验删除后为 0。
  - 安全护栏：某 workspace 在 suffixed 表已有数据时要求显式 `--force` 才允许清理其 legacy 行；脚本幂等（重跑删除 0 行）；预期失败退出码 2，错误输出经 DSN 脱敏。
- 执行顺序（维护窗口）：`pg_dump --data-only -t <表>`（pg_dump 默认单快照一致性）备份 3 张 legacy 表与身份表到仓库外目录 → 停止 API/Worker → 运行 `--apply` → 重启 API/Worker → 验收。
- 无应用代码变更、无公共 API/数据库模式变更；空 legacy 表保留且无害（守卫按行数判定为 0），不 DROP。

## Capabilities

### New Capabilities
- `legacy-embedding-vector-purge`: 一次性清空 legacy 无后缀向量表并注册 canonical embedding 身份，使存量 KB 恢复初始化和查询的运维能力。

### Modified Capabilities

<!-- 无既有 spec 需求变更 -->

## Impact

- `scripts/` 新增一个幂等运维脚本（asyncpg，接 `DATABASE_URL`，退出码 0 成功 / 2 预期失败）。
- PostgreSQL：3 张 legacy 向量表中 7 个 workspace 的行将被删除（执行前必须通过备份门禁）；`kb_text_embedding_identities` 新增至多 7 行注册（INSERTED/EXISTED 可追溯）。
- `LIGHTRAG_DOC_STATUS` / `LIGHTRAG_DOC_CHUNKS` 及各 KB 本地 graphml/vdb-json 不清理：旧文档仍显示但不可检索，重新上传同一文件不受影响（去重为进程内临时记录）。
- 维护窗口内需停止 API/Worker；脚本另以 workspace 级 advisory lock 提供机制级并发防护。
- 回滚预案：恢复 dump 中的 legacy 行 + 仅删除脚本标注为 `INSERTED` 的身份注册行。