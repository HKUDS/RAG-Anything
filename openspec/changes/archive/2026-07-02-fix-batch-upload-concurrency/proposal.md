## Why

批量上传时，`upload_files` 端点将所有文件同时加入 `BackgroundTasks`，导致 N 个 Worker 子进程并发读写同一个知识库的 LightRAG 存储（JSON 文件），引发竞态条件、进程崩溃，最终大量文件处理失败。`max_concurrent_files = 1` 配置已存在但未被上传端点使用。

## What Changes

- 在批量上传端点接入 `max_concurrent_files` 并发限制，确保同一 KB 同时只有 1 个 Worker 在处理
- 超出并发上限的文件排入等待队列，当前文件完成后自动触发下一个
- 单文件上传端点同样受此限制保护

## Capabilities

### New Capabilities
- `upload-concurrency-control`: 上传端点基于 KB 的并发控制，防止多 Worker 同时竞争同一 LightRAG 存储

### Modified Capabilities
<!-- None — existing specs (upload-dedup-guard, worker-file-lock) cover different concerns and are unchanged. -->

## Impact

- **Affected code**: `raganything/routers/knowledge.py` (`upload_file`, `upload_files`), `raganything/services/kb_service.py` (`_process_uploaded_file`)
- **Config**: 使用已有的 `max_concurrent_files` 配置项（默认 1）
- **Breaking**: 无 — 单文件上传行为不变，批量上传从"全部并发崩溃"变为"逐个排队处理"
