## Context

RAG-Anything 采用主进程/子进程架构：`server.py`（Uvicorn/FastAPI）接收上传请求，通过 `kb_service.py` 以 `asyncio.create_subprocess_exec` 启动 `process_worker.py` 子进程完成文档解析、实体提取和图谱构建。当前架构沒有任何进程互斥机制：

- **Server 层面**：无 PID 文件或端口检测，用户可能无意中启动多个 uvicorn 实例
- **API 层面**：同一文件可被多次提交上传，`processing_tasks` 字典仅按 task_id 索引，不按文件去重
- **Worker 层面**：多个 Worker 可能同时处理同一文件，导致 doc_status 写入冲突

历史故障记录：
- 2026-06-19：同时运行 2 个 Server（PID 30072 venv + 30088 system Python）+ 2 个 Worker（PID 19868 + 15680）
- 2026-06-22：再次出现 2 个 Worker（PID 27932 + 15208）同时处理同一文件

### 约束条件
- 必须跨平台（Windows + Linux/Mac）
- 不能引入新的外部依赖（使用 Python 标准库）
- 不能改变现有 API 契约（新增 409 状态码属标准 HTTP 语义）
- Process lock 必须在进程异常退出时自动释放（不能留下僵尸锁）

## Goals / Non-Goals

**Goals:**
- 防止同一端口被多个 Server 实例占用
- 防止同一文件的上传请求被重复提交（API 层面）
- 防止同一文件被多个 Worker 同时处理（OS 文件锁）
- Worker 异常退出时自动释放锁，不留僵尸锁

**Non-Goals:**
- 不实现分布式锁（当前是单机部署）
- 不修改 LightRAG 内部的并发模型
- 不实现跨服务器的全局任务队列
- 不处理不同 KB 下同名文件的并发（不同 KB 独立存储，天然隔离）

## Decisions

### Decision 1: PID 文件 + 端口检测双重保险

**选择**：Server 启动时同时检查 PID 文件和管理端口绑定。

- PID 文件：`<working_dir>/.server.pid`，包含进程 PID 和启动时间
- 端口检测：启动前 `socket.bind()` 测试目标端口是否空闲
- 僵尸清理：读取 PID 文件后检查该 PID 是否还存在，不存在则视为过时并覆盖

**Alternatives considered**:
- 仅 PID 文件 → PID 可能被复用，误判
- 仅端口检测 → 不同端口仍可启动多实例
- `flock` 系统调用 → 不跨平台，Windows 不支持

### Decision 2: `msvcrt` (Windows) / `fcntl` (Unix) 双轨文件锁

**选择**：在 `raganything/utils/process_lock.py` 中封装跨平台文件锁，Windows 使用 `msvcrt.locking`，Unix 使用 `fcntl.flock`。

```python
class FileLock:
    def __init__(self, lock_path: str): ...
    def acquire(self, timeout: float = 0) -> bool: ...
    def release(self): ...
    def __enter__(self): ...
    def __exit__(self): ...
```

- Lock 文件路径：`<kb_workspace>/<file_hash>.lock`
- 锁随进程退出自动释放（OS 级别保证）
- 非阻塞获取失败时返回 False（不等待）

**Alternatives considered**:
- `portalocker` 库 → 引入外部依赖，不符合约束
- `filelock` 库 → 同上
- `tempfile` + `os.unlink` → 无法处理进程崩溃
- 数据库行锁 → 需要额外的状态表，过度设计

### Decision 3: 上传 API 返回 409 Conflict（非阻塞排队）

**选择**：当同一文件已有进行中的处理任务时，拒绝新请求并返回 HTTP 409 Conflict，附带现有任务 ID。

- 按 `(kb_name, file_hash)` 作为去重键
- 文件 hash 使用 SHA256 前 16 字符
- 不实现自动排队（可能造成无限队列），由前端决定是否重试

**Alternatives considered**:
- 自动排队 → 用户上传后"假成功"体验更差，队列可能无限增长
- 静默忽略 → 用户不知道发生了什么
- 覆盖前一个任务 → 可能导致数据损坏

### Decision 4: Worker 启动前检查 + 文件锁双重保障

**选择**：在每个 Worker 实际处理文件前，进行两级检查：
1. **应用层检查**：查询 `doc_status`，如果 `status == "processing"` 且 `updated_at` 在阈值内（如 5 分钟），认为有活跃 Worker
2. **OS 文件锁**：获取 `<file>.lock` 的排他锁。如果获取失败，说明另一个 Worker 正在处理

如果任一层失败，Worker 以非零退出码退出，Server 将任务标记为失败。

## Risks / Trade-offs

- [风险] PID 文件残留 → 缓解：启动时验证 PID 是否存活；Server 注册 `atexit` 清理
- [风险] NFS/网络文件系统上的文件锁不可靠 → 缓解：当前仅支持本地文件系统部署，文档明确此限制
- [风险] 文件锁路径与 KB workspace 耦合 → 缓解：lock 文件放在 KB workspace 之外（`<working_dir>/.locks/`），统一管理
- [权衡] 拒绝而非排队 → 用户需要手动重试上传，但避免了"假成功"陷阱

## Migration Plan

1. 部署新版本代码
2. 重启 Server（新 PID 文件机制在启动时生效）
3. 清理历史僵尸文件：`find . -name "*.lock" -delete`
4. 无需数据迁移

## Open Questions

- _无_ — 所有技术决策已在上述 Decisions 中确定。
