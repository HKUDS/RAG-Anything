## 1. 文档名持久化重建（citation-source-tracing）

- [x] 1.1 在 `raganything/processor/chunk_processor.py` 的 `_ensure_chunk_source_cache` 增加 PG 分支：`getattr(doc_status_store, "db", None) is not None` 时经 `doc_status_store.db.query(..., multirows=True)` 按 `doc_status_store.workspace` 查询 `LIGHTRAG_DOC_STATUS`（`file_path`、`chunks_list`，过滤空 `file_path` 与 NULL `chunks_list`）
- [x] 1.2 实现 `chunks_list` 三态解析（str→`json.loads` 失败按 `[]`、list 直接用、None→`[]`）并逐行容错；文档名经 `_get_file_reference(file_path)` 生成
- [x] 1.3 将一次性 `_built` 标志改为 TTL 刷新（60 秒）+ 实例级 `asyncio.Lock`；失败不标记成功以便下次重试
- [x] 1.4 保持 JSON 存储 `_data` 路径不变并加 `_data is not None` 守卫

## 2. 受控媒体根扩展（query-endpoint-image-discovery）

- [x] 2.1 在 `raganything/services/odl_media_delivery.py` 提取模块级 `_project_root()`，`_controlled_roots()` 改用它
- [x] 2.2 `_controlled_roots()` 追加项目根下名称精确为 `output` 或以 `output_` 开头的现有目录（`is_dir`、拒绝符号链接根、`resolve` 去重），以及调用时 `os.getenv("OUTPUT_DIR", "./output")` 的绝对化目录
- [x] 2.3 为 `_controlled_roots()` 增加 10 秒进程级 TTL 缓存与 `_reset_controlled_roots_cache()` 测试钩子

## 3. 测试

- [x] 3.1 新增 `_ensure_chunk_source_cache` PG 重建单元测试（伪 `db`/`workspace`、三态 `chunks_list`、失败不置成功、TTL 刷新、JSON 回归）
- [x] 3.2 新增 `_controlled_roots()` 单元测试（monkeypatch `_project_root()`；`output`/`output_*`/`OUTPUT_DIR` 放行、项目外拒绝、符号链接过滤、缓存重置）
- [x] 3.3 运行 `tests/test_query_image_recall.py`、`tests/test_query_execution_deadline.py`、`tests/testodl_media_delivery.py` 及新增用例全量回归（定向 pytest 通过、`py_compile`、`git diff --check`）

## 4. 收尾

- [x] 4.1 按铁律完成 apply 两级调度（执行、审查、测试三专家）并复核验证结果
- [x] 4.2 同步 `PROJECT_SUMMARY.md` 当前事实并追加近期任务记录
