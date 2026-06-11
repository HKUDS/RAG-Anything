## Why

子进程（`process_worker.py`）在处理文档时，多模态内容（VLM 图片描述、LLM 表格分析）被调度为后台异步任务（`asyncio.create_task()`）执行。但子进程的主协程在文本入库完成后立即返回，导致 Python 进程退出，后台多模态任务被强制终止。结果：文档状态被父进程标记为 `failed`，多模态数据（图片描述、表格分析）丢失。

## What Changes

- **子进程等待后台任务完成**：在 `process_file()` 返回前，等待所有后台多模态处理任务完成后再退出
- **后台任务注册机制**：提供统一的 pending task 追踪，确保子进程退出前所有异步任务已结算
- **超时兜底**：设置最大等待时间，防止单条多模态处理挂死导致子进程永远不退出
- **状态同步**：多模态处理完成后正确更新 doc_status，而非残留 `failed` 状态

## Capabilities

### New Capabilities
- `background-task-lifecycle`: 子进程后台异步任务生命周期管理——确保进程退出前所有 pending 任务完成，含超时兜底

### Modified Capabilities
<!-- None; existing specs (bm25-keyword-index, graph-channel-retrieval, rrf-hybrid-search) are unrelated. -->

## Impact

- `process_worker.py`: `process_file()` 主函数，增加后台任务等待逻辑
- `raganything/processor.py`: `_process_multimodal_content_background()` 和 `insert_content_list()`，可能需要暴露任务引用
- `server.py`: `PROCESS_TIMEOUT` 相关的超时处理
