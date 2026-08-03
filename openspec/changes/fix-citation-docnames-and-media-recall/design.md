## Context

知识库问答的引用来源依赖 `_chunk_source_cache`（进程内内存缓存）。该缓存只在文档处理期（`_register_chunk_sources`）或惰性重建（`_ensure_chunk_source_cache` 遍历 `doc_status._data`）时填充；`PGDocStatusStorage` 的 `get_by_id`/`get_by_ids` 直接查库、从不写 `_data`，故 PG 部署下服务重启后缓存恒空，引用退化为“未知文档”。

图片交付链路：`recall_query_images` 三段召回（上下文直提 → BM25/二元组扫描 → 图谱）→ `_validate_image_paths`（受控根校验）→ `_controlled_recalled_media`（目录匹配或 chunk 证据 legacy grant）→ 前端“引用来源”区。项目自有解析产物位于项目根下 `output`/`output_*` 目录，不在 `ODL_ARTIFACT_ROOT`/`ODL_LEGACY_MEDIA_ROOTS`/`odl-artifacts` 受控根内，全部被 `outside_controlled_root` 拒绝。

## Goals / Non-Goals

**Goals:**
- 服务重启后引用来源显示真实文档名（PG 与 JSON 存储均正确）。
- 项目自有解析产物（`output*`）中的图片可经既有证据链召回并交付。
- 保持既有安全模型：受控根 + 所有权证据 + KB 绑定 grant。

**Non-Goals:**
- 不改前端、不改三段式召回与 3 张上限、不改媒体时间预算。
- 不写“重新解析 `odl解析` 库”的代码（运维项）。
- 不引入数据库迁移或新依赖。

## Decisions

### 决策 1：PG 重建使用 `doc_status_store.db` 而非 `get_pg_pool()`
通过存储对象自带的 `PostgreSQLDB` 执行 `SELECT file_path, chunks_list FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1`（`multirows=True`）。理由：与 LightRAG 存储同库（构造保证），避免 Core 层依赖 Service 层 `pg_state_repo` 违反分层方向；`db.query` 与 LightRAG 内部调用同构。备选（`get_pg_pool`）被否决：引入“状态池与 LightRAG 同库”的隐含假设且破坏依赖方向。

### 决策 2：PG 检测与 JSON 回归保护
使用 `getattr(doc_status_store, "db", None) is not None` 判定 PG 分支；`JsonDocStatusStorage` 无 `db` 属性，直接属性访问会抛 `AttributeError` 并被外层吞掉导致缓存永不构建。JSON 分支保留原 `_data` 遍历并加 `_data is not None` 守卫。

### 决策 3：TTL 刷新 + 实例级锁
将一次性 `_chunk_source_cache_built` 改为“构建时间戳 + 60 秒 TTL”：过期后重新重建；`asyncio.Lock` 防止并发首个查询重复重建。理由：worker 子进程后续写入的新文档不会进入 API 进程缓存，一次性构建会再次退化。失败不更新时间戳，下次查询重试。

### 决策 4：chunks_list 三态解析与逐行容错
`chunks_list` 为 JSONB：`str → json.loads`（解析失败按 `[]`）、`list` 直接用、`None → []`；单行坏数据跳过不中断整批；SQL 过滤 `file_path <> '' AND chunks_list IS NOT NULL`。

### 决策 5：受控根精确匹配 + 短 TTL 缓存
`_controlled_roots()` 在现有 ODL 环境变量根与 `odl-artifacts` 之外，追加：项目根下名称精确等于 `output` 或以 `output_` 开头的现有目录（`is_dir()`、拒绝符号链接根、`resolve()` 去重），以及调用时 `os.getenv("OUTPUT_DIR", "./output")` 的绝对化目录（运行时覆盖可见）。避免 `output*` glob 误匹配 `outputs`/`output-backup`。媒体召回是热点路径，增加 10 秒进程级 TTL 缓存与 `_reset_controlled_roots_cache()` 测试钩子；项目根提取为模块级 `_project_root()` 便于 monkeypatch。

### 决策 6：安全模型
保留交付顺序：ODL 目录匹配优先，chunk 证据 legacy grant 兜底；grant 绑定 KB、文档、chunk 并带 sha256 与 TTL；serve 端每次重校验后缀/受控根/符号链接/regular file/mime/摘要。受控根扩大后，已认证用户可经“自己 KB chunk 写入已知绝对路径”读取 `output*` 图片——与 `odl-artifacts` 既有模型一致，显式记录该威胁模型并接受。

## Risks / Trade-offs

- [跨 KB 知识型读取面扩大] → 交付仍要求同 KB chunk 内容证据 + KB 绑定 grant + sha256 + TTL；受控根仅限项目自有 `output`/`output_*`/`OUTPUT_DIR`，不扩大到任意路径；威胁模型写入设计文档。
- [TTL 窗口内新文档引用短暂不更新（≤60s）] → 60 秒内自动刷新，可接受；失败不置成功标志。
- [首次查询增加一次 DB 往返] → 单条 SQL + 索引支撑 + 仅取非空行；重建后 TTL 期内不再往返。
- [JSON 存储回归] → `getattr(db)` 检测 + `_data is not None` 守卫 + 回归测试。
- [受控根缓存导致测试/配置漂移] → 10s TTL + `_reset_controlled_roots_cache()` 钩子 + 测试统一 monkeypatch `_project_root()`。

## Migration Plan

无数据库迁移与 API 变更。部署：更新两个后端文件与测试后重启服务；验证方式见测试计划；回滚为撤销本次提交并重启。

## Open Questions

无阻塞项。`odl解析` 知识库重新解析属运维项，不依赖本变更。
