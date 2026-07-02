## 1. 基础设施：Per-KB 队列

- [x] 1.1 在 `shared.py` 中添加 `_kb_queues: dict[str, asyncio.Queue] = {}` 和 `_kb_draining: dict[str, bool] = {}`
- [x] 1.2 从 `config.py` 读取 `max_concurrent_files` 到 shared 模块（`_MAX_CONCURRENT_FILES`）

## 2. Drain 协程

- [x] 2.1 在 `kb_service.py` 新增 `_drain_kb_queue(kb_name: str)` async 函数：循环从 `_kb_queues[kb_name]` 取任务，逐个 `await _process_uploaded_file()`，队列空时退出
- [x] 2.2 Drain 内每个文件用 `try/except` 包裹，单个失败不中断循环
- [x] 2.3 使用 `_kb_draining` 标志位防止重复启动 drain

## 3. 上传端点改造

- [x] 3.1 修改 `upload_file` 端点：将 `background_tasks.add_task(_process_uploaded_file, ...)` 替换为 `_kb_queues[kb].put_nowait(task_info)` + 按需启动 drain
- [x] 3.2 修改 `upload_files` 端点：将所有文件推入队列，按需启动 drain
- [x] 3.3 响应体增加 `position` 和 `queue_size` 字段
- [x] 3.4 Drain 启动使用 `asyncio.ensure_future`（通过 `_ensure_queue_draining`）

## 4. WebSocket 通知适配

- [x] 4.1 更新 `processing_tasks` 的 task_id 粒度：每个文件仍是独立 task_id，前端可逐个追踪（`_process_uploaded_file` 内部逻辑未变）
- [x] 4.2 队列位置变化时通过 WebSocket 推送 `queue_position` 事件

## 5. 验证

- [x] 5.1 语法检查：确认 `knowledge.py`、`kb_service.py`、`shared.py` 无语法错误
- [ ] 5.2 队列测试：上传 3 个文件到同一 KB，确认逐个处理（日志中 Worker 串行启动） — 需重启后端后手动测试
- [ ] 5.3 混合测试：先上传 1 个文件，处理中再上传 2 个文件，确认都排队成功 — 需重启后端后手动测试
- [ ] 5.4 跨 KB 测试：KB-A 排队处理时，上传到 KB-B，确认立即处理（独立队列） — 需重启后端后手动测试
