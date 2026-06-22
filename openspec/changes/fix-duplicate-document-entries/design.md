## Context

RAG-Anything 在上传文档时使用 `secrets.token_hex(4)` 生成 8 字符 hex 前缀来避免磁盘文件名冲突（如 `593dbd4b_测试.docx`）。但当前系统中存在三处文件名引用的不一致：

1. **`processing_tasks`**（内存字典）：存储原始文件名 `测试.docx`
2. **`kv_store_doc_status.json`**（磁盘持久化）：存储 hash 前缀文件名 `593dbd4b_测试.docx`
3. **`_get_file_reference()`**（`chunk_processor.py`）：`use_full_path=False` 默认返回 hash 前缀的 basename

`list_documents` 端点合并两个数据源时，用 `seen_files` 集合做去重，但两个来源的文件名格式不同，导致去重永远失败。

此外，`cleanup_completed_tasks()` 函数存在于 `state_service.py` 但从未被调用，且 `doc_status` 旧条目永久累积。

## Goals / Non-Goals

**Goals:**
- 修复 `list_documents` 中的文件名去重逻辑，确保同一次上传只在列表中显示一条记录
- 在返回列表前清理 `processing_tasks` 中已完成的任务条目
- 对于同名文档的多次上传，只保留最新的 doc_status 记录

**Non-Goals:**
- 不改变磁盘文件命名策略（hash 前缀保留，避免文件冲突）
- 不改变 `processing_tasks` 和 `kv_store_doc_status` 的数据结构
- 不修改前端轮询逻辑
- 不添加数据库迁移

## Decisions

### 决策1：在 `list_documents` 层修复去重，而非存储层

**选择**：在 `list_documents` 响应构建时统一文件名格式进行去重。

**替代方案**：
- 方案 A（已拒绝）：修改 `processing_tasks` 存储 hash 前缀文件名。问题：需要改动多处写入逻辑，且 hash 前缀在写入时可能尚未确定。
- 方案 B（已拒绝）：修改 `kv_store_doc_status` 存储原始文件名。问题：多文档同名时无法区分，且需要数据迁移。

**理由**：修复在展示层（API 响应构建）是最小改动，不改变数据模型，不影响其他消费者。

### 决策2：Hash 前缀剥离使用正则模式 `^[0-9a-f]{8}_`

**选择**：使用正则 `^[0-9a-f]{8}_` 匹配并剥离 hash 前缀。

**理由**：`secrets.token_hex(4)` 产生 8 个小写 hex 字符，此模式精确匹配。提取辅助函数 `_strip_hash_prefix(filename)` 便于复用和测试。

### 决策3：在 `list_documents` 中清理已完成任务

**选择**：在 `list_documents` 响应构建前过滤已完成任务，而不是引入定时器或后台线程。

**理由**：
- 不需要引入额外的调度基础设施
- `list_documents` 每 8 秒被前端轮询，清理频率足够
- 简单、同步、无竞态条件

### 决策4：同名旧 doc_status 条目清理策略

**选择**：在 `list_documents` 中检测同一原始文件名的多个 doc_status 条目，只展示最新（按 `updated_at` 排序）的那条。

**理由**：避免磁盘写入操作在读取路径中，保持 `list_documents` 为纯读取操作。旧条目最终可通过未来的维护任务清理。

## Risks / Trade-offs

- **[风险] 非 hex 前缀文件名误匹配** → 缓解：正则严格匹配 8 位小写 hex + 下划线，普通文件名不受影响
- **[风险] `cleanup_completed_tasks` 首次调用可能清理正在写入的任务** → 缓解：清理前检查 `status == "completed"`，只移除明确标记为已完成的任务
- **[权衡] 旧 doc_status 条目不在请求路径中删除** → 仅隐藏不删除，磁盘空间缓慢增长。后续可通过独立维护 PR 添加定期清理
