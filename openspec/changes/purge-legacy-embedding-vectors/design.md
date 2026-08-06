## Context

部署 embedding 身份后，`ensure_kb_embedding_identity`（`raganything/services/pg_embedding_identity.py`）在 LightRAG 初始化前对含 legacy 无后缀向量行的 workspace fail-closed 抛出 `embedding_legacy_storage_incompatible`。实测 7 个存量 workspace（视频、odl解析、新能源、odl图片修复2.0/4.0、odl解析_图片修复、测试）受影响：legacy 表 `lightrag_vdb_chunks/entity/relation` 合计 4047/19124/48290 行，新后缀表均为 0 行，身份表仅注册了 `./rag_storage`、`./rag_storage_autorepair` 与两个临时 upload 工作区。用户决定：清空 legacy 向量、不改守卫代码。

## Goals / Non-Goals

**Goals:**
- 提供幂等、可审计的一次性脚本清空 legacy 向量行并注册 canonical embedding 身份，使存量 KB 恢复初始化与查询。
- 执行前强制备份校验，执行后自动校验行数与身份注册。
- 全程不改应用代码、不引入公共 API/模式变更。

**Non-Goals:**
- 不迁移/保留旧向量数据（用户已确认清空）。
- 不清理 `LIGHTRAG_DOC_STATUS` / `LIGHTRAG_DOC_CHUNKS` 及各 KB 本地 graphml/vdb-json。
- 不修改守卫逻辑；不解决大视频 HNSW OOM（既有独立计划）与启动期 PG 连接池瞬时耗尽。

## Decisions

- **运维脚本而非代码修改**：守卫语义保留，脚本把 legacy 行清空并注册身份后守卫自然放行；避免削弱 fail-closed 安全属性。
- **权威身份来源**：以 `kb_text_embedding_identities` 中 `./rag_storage` 的 identity JSON 为唯一权威来源；脚本必须与生产 API/Worker 相同的 embedding env（`EMBEDDING_PROVIDER/MODEL/DIM`、`EMBEDDING_ENDPOINT_SEMANTICS` 或 `LLM_BINDING_HOST`）运行，并用 `canonical_text_embedding_identity` 从运行时 env 重算逐字段交叉校验；来源行缺失、env 不一致或存在与权威身份不一致的其他注册时 dry-run/apply 均 fail-closed 中止，避免注册错误身份导致 `embedding_identity_conflict`。
- **目标 workspace 冲突注册校验**：apply 事务内对每个受影响 workspace `SELECT ... FOR UPDATE` 现有注册：无行→INSERT；有行→逐字段比对权威身份，不一致立即中止并整体回滚，一致则标记 EXISTED 不重复写入（与守卫的 conflict 语义一致，拒绝 `ON CONFLICT DO NOTHING` 静默放行）。
- **表发现与守卫同源**：legacy 表用 `information_schema` 大小写不敏感匹配 `LIGHTRAG_VDB_%` 且要求存在 `workspace` 列，与 `_legacy_rows` 判定一致；suffixed 表同样枚举（`LIGHTRAG_VDB_%` + `workspace` 列 + 不在 legacy 集合），按 workspace 聚合输出孤儿行清单；拼接 SQL 前用安全表名校验并双引号包裹实际物理表名。
- **孤儿行安全护栏**：某 workspace 在任意 suffixed 表已有数据时，默认拒绝清理其 legacy 行并要求显式 `--force`；`--force` 仅与 `--apply` 组合有效，输出中记录 force 放行清单。
- **单事务 + 逐 workspace 校验 + advisory lock**：身份注册与 DELETE 在同一事务；每个 workspace 先取 `SELECT pg_advisory_xact_lock(hashtext($1))`（与守卫同 key），把并发防护从“维护窗口停机”的过程约定升级为机制保证；每个 workspace 删除后立即校验 legacy 计数为 0，任一失败整体回滚。
- **apply 事务内重新发现**：不依赖 dry-run 输出，apply 在事务内动态枚举受影响 workspace，避免两次运行之间出现新 workspace 被漏清。
- **备份门禁**：`--apply` 必须提供 `--backup-dir`；脚本在执行任何写操作前校验每张实际存在的 legacy 表都有对应非空 dump 文件且包含该表 `COPY public.<table>` 数据，任一不满足即以退出码 2 拒绝。备份命令使用 `pg_dump --data-only -t <table>`（pg_dump 默认从单一快照导出，一致性有保证；`--single-transaction` 是 pg_restore 选项，不适用于 pg_dump）。
- **幂等**：重复 `--apply` 时发现 0 行，报告 0 删除并以 0 退出；无 legacy 行时不写任何身份注册。
- **回滚预案可执行**：脚本输出按 workspace 标注 `INSERTED/EXISTED`；回滚=恢复 dump（legacy 行）+ 仅删除脚本标注为 `INSERTED` 的身份行（EXISTED 行非脚本新增，不得删除），随后重启验收。建议 dump 一并包含 `kb_text_embedding_identities` 表以便完整复原。
- **错误处理与脱敏**：预期失败（护栏/备份门禁/身份冲突/连接失败）以退出码 2 结束并给出可操作提示；错误输出经 DSN 脱敏，不包含密码或完整连接串；脚本运行时拒绝 `PG_WORKSPACE` 环境残留（与 `assert_workspace_override` 语义一致）。

## Risks / Trade-offs

- [删除不可恢复] → 强制备份门禁 + `--single-transaction` 一致快照 + 单事务；回滚=恢复 dump + 按 `INSERTED/EXISTED` 清单删除新增身份行。
- [身份与运行时 env 不一致] → 权威来源（`./rag_storage`）与 env 重算双重校验，不一致即中止。
- [目标 workspace 已有冲突注册] → `FOR UPDATE` + 逐字段比对，冲突即回滚，杜绝“清空后仍被守卫阻断”的二次维护窗口。
- [suffixed 孤儿行] → dry-run 全量清单 + `--force` 护栏；默认拒绝，避免清空后旧数据不可检索却无人知晓。
- [空 legacy 表残留] → 脚本只删行不 DROP；LightRAG 建表为 if-not-exists，不会自动删除空表，空表保留且无害（守卫按行数判定为 0），如需物理清理另行评估显式 DROP 步骤。
- [旧文档仍显示但不可检索] → 与用户决策一致；重新上传同文件会生成新文档（去重为进程内临时记录）。
- [并发初始化竞态] → 维护窗口停 API/Worker + 事务内 workspace 级 advisory lock 双重防护。 备份与维护窗口（执行顺序）：`pg_dump --data-only` 备份 3 张 legacy 表到 `C:\tmp\legacy_vdb_backup_<时间戳>\`（仓库外）→ 停止 API/Worker（暂停上传与写入）→ 运行 `--apply` → 重启 API/Worker。清空后 legacy 空表由 LightRAG 下次初始化自然删除，无需手动 DROP。