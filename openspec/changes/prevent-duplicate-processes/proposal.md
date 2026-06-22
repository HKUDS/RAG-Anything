## Why

RAG-Anything 的主进程/子进程架构缺乏进程互斥机制，导致服务器重复启动、同一文件被多个 Worker 同时处理等问题。该问题在实际使用中已发生 2 次（双服务器 + 双 Worker），导致资源浪费、文档状态混乱，以及用户看到的"假失败"状态。必须在架构层面建立防御纵深，杜绝重复进程。

## What Changes

- **新增 Server PID 文件锁**：服务器启动时检查/创建 PID 文件，防止同时运行多个服务器实例
- **新增上传 API 去重**：在上传端点层面检测同一文件是否已有在处理中的任务，拒绝重复提交
- **增强文件处理检查**：在 `_process_uploaded_file` 中增加处理中状态检测，Worker 启动前确认无冲突
- **新增 Worker 文件级锁**：Worker 子进程对正在处理的文件获取排他锁，防止并发处理同一文件
- **新增过时 PID 文件清理**：进程退出时清理 PID 文件，启动时清理僵尸 PID 文件

## Capabilities

### New Capabilities
- `server-startup-lock`: 服务器启动互斥锁（PID 文件 + 端口检测），防止多实例
- `upload-dedup-guard`: 上传 API 层面去重保护，拒绝同一文件的并发上传请求
- `worker-file-lock`: Worker 子进程对处理文件的排他锁，确保同文件单 Worker

### Modified Capabilities
<!-- No existing specs need modification at requirement level -->

## Impact

- **Affected code**: `server.py`（启动逻辑）、`raganything/services/kb_service.py`（`_process_uploaded_file`、上传处理入口）、`process_worker.py`（Worker 启动前检查）
- **New files**: `raganything/utils/process_lock.py`（通用进程锁工具模块）
- **No API breaking changes**: 所有改动的行为对 API 消费者透明，仅在冲突场景下返回 409 Conflict
- **No dependency changes**: 使用 Python 标准库 `fcntl`/`msvcrt`/`os` 实现文件锁
