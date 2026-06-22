## Why

上传 .docx 文档后，前端显示"已完成"（有实体数和关系数），但实际 entity/relation/graph/vector 数据全部未写入磁盘，导致查询返回 0 结果。根因是 worker 子进程在 doc_status 已被 LightRAG 内部标记为 `failed` 时仍以 exit code 0 退出，主进程无法感知失败；同时缺少后处理数据验证环节。

## What Changes

- **Worker 进程失败检测修正**：doc_status 为 `failed` 或 `chunks_count == 0` 时均以 exit code 1 退出，确保主进程能捕获失败
- **后处理数据验证**：Worker 完成后，主进程验证 `kv_store_doc_status.json` 中对应文档的 `chunks_count > 0`，否则将任务标记为 `failed`
- **`process_document_complete` 添加 `_insert_done()` 调用**：与纯文本路径 `insert_content_list` 保持一致，确保 entity/relation 数据持久化到磁盘
- **`finalize_storages` 异常日志**：将静默 `pass` 替换为 warning 日志，便于排查持久化失败

## Capabilities

### New Capabilities

- `upload-failure-detection`: 上传处理管道的失败检测机制，确保 worker 子进程的任何失败（包括 LightRAG 内部静默失败）都能被主进程捕获并正确反映在任务状态中

### Modified Capabilities

<!-- No existing specs have requirement-level changes -->

## Impact

- **Worker 子进程**：`process_worker.py` — 失败判定逻辑修改
- **主进程上传处理**：`raganything/services/kb_service.py` — 添加后处理验证、`finalize_storages` 异常日志
- **文档处理器**：`raganything/processor/doc_processor.py` — `process_document_complete` 末尾添加 `_insert_done()`
- **前端**：无需修改（状态字段已支持 `failed`）
