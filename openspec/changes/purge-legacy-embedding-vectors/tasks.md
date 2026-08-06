## 1. 提案与评审

- [x] 1.1 完成 proposal/design/specs/tasks 全部工件
- [x] 1.2 至少 2 位专家评审提案并吸收反馈（备份门禁、冲突注册校验、advisory lock、孤儿行、脱敏/退出码已并入本版）

## 2. 脚本实现

- [x] 2.1 实现 `scripts/purge_legacy_embedding_vectors.py`：`--dry-run` 默认发现 legacy 表与全部 suffixed 表（information_schema 大小写不敏感 + workspace 列 + 安全表名引用），输出行数基线与孤儿行清单
- [x] 2.2 实现 `--apply`：单事务内取 workspace advisory lock、以 `./rag_storage` 为权威身份并交叉校验 env、逐 workspace `FOR UPDATE` 冲突校验（INSERTED/EXISTED）、DELETE legacy 行、逐表校验 0 行
- [x] 2.3 实现安全护栏与备份门禁：suffixed 有数据需 `--force`；`--apply` 必须 `--backup-dir` 且校验 dump 文件存在/非空/含 COPY；`PG_WORKSPACE` 残留拒绝；幂等重跑报告 0 删除
- [x] 2.4 编写脚本自检测试（`tests/test_purge_legacy_embedding_vectors.py`）：dry-run 基线、0 workspace、幂等、force 护栏、冲突注册中止、身份来源缺失/ env 不一致中止、备份门禁失败、缺表跳过、退出码与错误脱敏

## 3. 检查与提交

- [x] 3.1 `py_compile`、focused pytest（29 脚本自检 + identity/upload-retry/kb-mutation/migration 冒烟共 89 项）、OpenSpec strict、`git diff --check` 全部通过
- [ ] 3.2 更新 `PROJECT_SUMMARY.md` 并提交本变更

## 4. 生产执行（维护窗口）

- [x] 4.1 `pg_dump --data-only -t <表>`（默认单快照一致性）备份三张 legacy 表（及 `kb_text_embedding_identities`）到仓库外目录并校验文件非空（行数 4047/19124/48290 与基线一致）
- [x] 4.2 停止 API/Worker（执行时无运行中的 API/Worker 进程）
- [x] 4.3 运行 `--apply --backup-dir <目录>`：7 个 workspace 全部 INSERTED、删除 71461 行、逐表校验 0 残留、退出码 0
- [x] 4.4 重启 API/Worker：server 启动探针 `/api/live` 返回 `{"status":"live"}`，启动日志无 `embedding_legacy_storage_incompatible`、无 `PG doc_status instance unavailable`
- [x] 4.5 验收（核心部分）：`create_rag` + `_ensure_lightrag_initialized` 对 视频/odl解析 均 `{'success': True}`，9 条身份注册落库；回滚预案已记录（恢复 dump + 删除 INSERTED 身份行）
- [ ] 4.6 验收（端到端剩余项，需外网 LLM/Embedding 可达环境）：上传小 MP4 → processed → 可检索 → 新向量写入 `..._openai_compa_639985a6e4b87473_1024d` 表；视频 KB 智能体 SSE 查询 outcome=ok（本地沙箱无外网，DashScope 不可达）