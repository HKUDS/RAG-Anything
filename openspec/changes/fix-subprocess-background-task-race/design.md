## Context

`process_worker.py` 是文档上传的独立子进程处理入口。其主函数 `process_file()` 调用 `processor.insert_content_list()` 完成文本入库和多模态调度。当前多模态处理（VLM 图片描述 + LLM 表格分析）通过 `asyncio.create_task()` 在后台异步执行，但子进程在 `insert_content_list()` 返回后立即退出，导致后台任务被强制终止。

**当前调用链：**
```
server.py: _process_uploaded_file()
  → subprocess: process_worker.py process_file()
    → processor.insert_content_list()
      → loop.create_task(_process_multimodal_content_background(...))  ← 后台任务
      → return  ← 子进程立即退出，任务被杀死
```

**相关文件：**
- `process_worker.py:350` — `process_file()` 入口
- `raganything/processor.py:2325` — `loop.create_task()` 调度点
- `raganything/processor.py:768` — `_process_multimodal_content_background()` 后台任务实现
- `server.py:706` — 父进程等待子进程超时（`PROCESS_TIMEOUT`，默认 3600 秒）

## Goals / Non-Goals

**Goals:**
- 子进程退出前等待所有后台多模态任务完成
- 提供统一的 pending task 追踪机制
- 设置最大等待超时防止永久挂起
- 正确同步 doc_status 状态

**Non-Goals:**
- 不改变多模态处理的异步/非阻塞架构
- 不修改父进程（`server.py`）的子进程管理逻辑
- 不改变 LightRAG 内部行为

## Decisions

### Decision 1: 模块级 Pending Task Registry

**选择：** 在 `processor.py` 中添加模块级 `asyncio.Event` 或 `set[asyncio.Task]` 来追踪 pending 的后台任务。

**备选方案：**
- ❌ 让 `insert_content_list()` 返回 task 引用：调用链太长，需要穿透多层
- ❌ 子进程轮询 doc_status：不可靠，且增加延迟
- ✅ 模块级 registry：最小侵入，`process_worker.py` 可以直接导入并等待

**实现：**
```python
# processor.py 模块级
_pending_background_tasks: set[asyncio.Task] = set()

def _register_background_task(task: asyncio.Task):
    _pending_background_tasks.add(task)
    task.add_done_callback(lambda t: _pending_background_tasks.discard(t))
```

### Decision 2: process_file() 等待逻辑

**选择：** 在 `process_file()` 的 finally 块中等待所有 pending tasks。

**实现位置：** `process_worker.py` 的 `process_file()` 函数末尾

```python
# 等待所有后台多模态任务完成
pending = processor.get_pending_background_tasks()
if pending:
    done, pending = await asyncio.wait(pending, timeout=BG_TASK_MAX_WAIT)
    if pending:
        print(f"[WORKER] 警告: {len(pending)} 个后台任务超时未完成")
```

### Decision 3: 超时时间

**选择：** `BG_TASK_MAX_WAIT = 1800`（30 分钟），可通过环境变量 `BG_TASK_MAX_WAIT` 覆盖。

**理由：** 75 个多模态条目逐条处理约需 30-50 分钟。设置 30 分钟可以在大部分场景下覆盖，同时避免永久挂起。用户可以通过环境变量调整。

## Risks / Trade-offs

- **[风险] 子进程退出延迟**：文本处理只需几十秒，但现在子进程要多等 30 分钟 → **缓解**：这是预期行为；文本分块已经立即可搜索（PROCESSED 状态在后台任务调度前已设置），多模态处理完成后只是增强数据
- **[风险] 超时后仍有数据丢失**：如果 75 条多模态超过 30 分钟还没跑完 → **缓解**：超时值可配置；已完成的部分已逐条入库（individual processing 模式下每条处理完立即 `_insert_done()`）
- **[权衡] 子进程内存占用**：等待期间子进程占用内存 → 可接受，子进程本来就存活期间需要内存

## Open Questions

- 是否需要将当前 KB "2" 的 `failed` 文档重新触发多模态处理？（建议：修复后再上传一次文档即可）
