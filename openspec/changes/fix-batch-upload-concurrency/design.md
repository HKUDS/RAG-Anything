## Context

当前 `upload_files`（批量上传）和 `upload_file`（单文件上传）端点将所有文件直接加入 `BackgroundTasks`，无并发控制。`process_worker.py` 有单文件级别锁（L3 doc_status 检查 + L4 FileLock），但仅防止同一文件被重复处理，不防止不同文件同时竞争同一 LightRAG 存储。

`max_concurrent_files = 1` 配置存在于 `config.py`，但仅在 `batch.py` 的 `process_folder_complete` 等内部批量操作中使用，上传端点未接入。

## Goals / Non-Goals

**Goals:**
- 单文件和批量上传统一使用 per-KB 处理队列，不再同时启动多个 Worker
- 队列为空时自动启动 drain，队列耗尽时自动退出
- 复用已有 `max_concurrent_files` 配置项
- 上传响应包含队列位置信息

**Non-Goals:**
- 不修改 `process_worker.py` 的锁机制
- 不引入消息队列、Celery 等外部依赖
- 队列不持久化（重启丢失，可接受）

## Decisions

### Decision 1: Per-KB `asyncio.Queue` + drain 协程

**选择**：在 `shared.py` 维护 `_kb_queues: dict[str, asyncio.Queue]` 和 `_kb_draining: dict[str, bool]`。两个上传端点都将文件信息推入队列。当队列从空变为非空时，用 `asyncio.create_task` 启动 `_drain_kb_queue(kb_name)` 协程。drain 协程逐个取出文件并 `await _process_uploaded_file()`，队列空时退出。

```
upload_file ──► _kb_queues[kb].put_nowait(task_info) ──┐
upload_files ──► for f in files: queue.put_nowait(...) ─┤
                                                        ▼
                                    _drain_kb_queue(kb) 循环
                                      └─ await _process_uploaded_file(task)
                                      └─ 下一项 ...
                                      └─ 队列空 → 退出
```

**替代方案**：
- *BackgroundTasks 串行包装器*：单文件上传无法加入同一后台任务 → 不统一
- *429 拒绝*：用户需要手动重试 → 体验差，用户明确要求排队
- *Celery/RQ 等外部队列*：引入新依赖 → 过度设计

**理由**：`asyncio.Queue` 是标准库，零依赖。`asyncio.create_task` 让 drain 协程存活于整个事件循环生命周期，不受单次 HTTP 请求限制。两个端点共享同一队列，统一了入口。

### Decision 2: 单 drain 协程而非 N 个并发 Worker

**选择**：每个 KB 只有 1 个 drain 协程，串行处理。`max_concurrent_files > 1` 的支持留待后续实现。

**替代方案**：
- *N 个并发 drain*：需要更复杂的并发计数和错误隔离 → 当前 `max_concurrent_files = 1` 不需要
- *Semaphore 控制*：多个 drain 同时运行但用 semaphore 限流 → 同样复杂

**理由**：`max_concurrent_files` 默认值为 1，先满足这个最常见场景。后续需要多并发时，只需让 drain 协程使用 Semaphore 控制并发数即可扩展。

### Decision 3: 队列位置反馈

**选择**：上传响应中包含 `position` 和 `queue_size` 字段，前端可展示预计等待时间。

**理由**：基于队列的架构天然知道队列中有多少项。给出位置信息比"已排队"更有用。

## Risks / Trade-offs

- **服务重启丢失队列**：Drain 协程和队列都在内存中，重启后丢失。
  → 缓解：上传文件已保存到 `uploads/` 目录，用户可通过前端"重试"按钮重新加入队列。

- **单 drain 故障阻塞整个 KB**：如果某个文件处理导致 drain 协程异常退出，后续文件将永远卡在队列中。
  → 缓解：drain 协程内 `try/except` 包裹单个文件处理，单个失败不中断循环。

- **Drain 协程泄漏**：如果 `create_task` 创建的 drain 协程因未捕获的异常退出，下次上传会启动新的 drain，但旧的任务引用可能残留。
  → 缓解：使用 `_kb_draining` 标志位 + `try/finally` 确保标志位正确复位。
