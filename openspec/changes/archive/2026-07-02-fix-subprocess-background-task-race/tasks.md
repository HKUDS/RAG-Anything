## 1. 后台任务注册机制

- [x] 1.1 在 `processor.py` 模块级添加 `_pending_background_tasks: set[asyncio.Task]` 集合
- [x] 1.2 实现 `register_background_task(task)` 函数：注册任务并设置 `add_done_callback` 自动清理
- [x] 1.3 实现 `get_pending_background_tasks()` 函数：返回当前 pending 任务集合的副本

## 2. 集成到现有流程

- [x] 2.1 在 `insert_content_list()` 的 `loop.create_task()` 调用后注册 background task
- [x] 2.2 确保 `_process_multimodal_content_background()` 的 finally 块在异常时也能触发 done callback（已由 `asyncio.Task.add_done_callback` 保证）

## 3. 子进程等待逻辑

- [x] 3.1 在 `process_worker.py` 的 `process_file()` 末尾添加 `await_pending_background_tasks()` 调用
- [x] 3.2 实现等待逻辑：使用 `asyncio.wait()` 等待所有 pending tasks，超时默认 1800 秒
- [x] 3.3 超时后记录未完成任务列表并输出警告日志
- [x] 3.4 支持 `BG_TASK_MAX_WAIT` 环境变量覆盖默认超时值

## 4. 验证与收尾

- [ ] 4.1 手动测试：上传包含图片/表格的文档，确认子进程等待多模态完成后再退出
- [ ] 4.2 手动测试：设置短超时（`BG_TASK_MAX_WAIT=5`），确认超时兜底生效、doc_status 正确标记为 failed
- [x] 4.3 确认现有测试（`tests/`）仍然通过，无回归 — 263 passed, 1 pre-existing failure (PARSER=docling env override)
