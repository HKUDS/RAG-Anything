## Context

上传抽屉已经持久化展示任务并每三秒轮询，但删除端点仅允许 `queued`。处理 worker、重试租约、任务状态和文档索引分别由多个服务维护，因此仅终止子进程会被失败收尾或重试重新写入。

## Goals / Non-Goals

**Goals:**
- 让授权用户永久删除 `queued`、`processing` 和 `retry_wait` 上传任务。
- 在释放文件哈希去重前停止同一任务的执行，并确保取消期间不会有完成、失败或重试回写。
- 以任务 ID、文件哈希和持久化来源限定部分入库内容的清理范围。
- 让前端明确展示服务端仍在完成取消，而不把 `202` 当作已经删除。

**Non-Goals:**
- 不取消浏览器尚未创建服务端任务的 HTTP 文件传输。
- 不改变已完成、失败或降级文档的删除入口，也不放宽活跃文档删除的 `409` 保护。
- 不引入新的客户端 API 或新的权限模型。

## Decisions

### Durable cancellation state

`queued` 继续使用现有同步 `deleted` 清理。`processing` 和 `retry_wait` 以数据库事务转换为 `cancelling`，清除处理 claim/心跳、使 generation 失效并取消关联重试 job；重复删除 `cancelling` 任务返回相同的 `202` 状态。迁移 `024` 将状态生命周期记录在数据库列说明中，不添加会拒绝历史状态的 CHECK 约束。

这样可以让 worker、重试 runner 和重启恢复都以同一个 durable state 判定取消，而非依赖单进程内存标记。直接标记为 `deleted` 被拒绝，因为旧 worker 仍可能写入索引或重新调度。

### Service-owned cancellation coordinator

`kb_service` 保存按任务 ID 的外层执行引用，并在取消时仅终止 `_kb_worker_procs` 中同一任务的子进程。协调器等待 worker 及外层协程在有界时间内退出；未完成时保留 `cancelling` 并由同一删除请求或恢复路径继续收敛。Router 只保留授权、读取和响应编排。

执行与所有收尾路径在写入 progress、completed、failed、retry 或 deferred work 前检查 durable cancellation。`state_service` 和 retry SQL 同样排除 `cancelling`，防止晚到回写使任务复活。

### Scoped cleanup and response contract

协调器在 worker 退出后查找具有本任务 `track_id`、任务元数据或文件哈希来源的文档；只有来源匹配时才复用完整文档删除的索引、向量、缓存、标签、修复、多模态和受控文件清理。随后删除任务状态、设置快照、重试 job 和暂存文件，最后 CAS `cancelling -> deleted` 并释放去重。

`DELETE /upload/tasks/{task_id}` 保持现有授权和路径。排队任务完成时返回 `200 deleted`；处理中或等待重试任务在未收敛时返回 `202 cancelling`，收敛后返回 `200 deleted`。终态任务返回 `409`，访问范围不匹配仍返回 `404`。`GET /upload/tasks` 仅对 `queued`、`processing`、`retry_wait` 返回 `can_delete=true`。

### Upload drawer feedback

排队任务删除成功后立即从本地列表移除。处理中和等待重试任务使用可访问确认对话框；接收 `202` 后保留卡片并显示取消中的状态，依赖现有轮询在服务端不再返回该任务时移除。确认、按钮文案和 ARIA 标签按任务状态变化；取消期间禁用重试操作。

### Document list deletion entry point

The document table SHALL expose the durable upload task ID supplied by the
document-list API when a row belongs to an unfinished upload. It MUST NOT
recover that ID by matching filenames. For `queued`, `processing`, and
`retry_wait` rows with this provenance, the table SHALL call the existing
upload-task deletion endpoint rather than the ordinary document deletion
endpoint. A `202 cancelling` response keeps the row visible with cancellation
feedback until the existing document-list polling observes its removal. The
confirmation dialog SHALL use the shared body portal so it remains centered in
the viewport regardless of the table's layout or route animation containers.

## Risks / Trade-offs

- [强制终止时已有部分索引] → 仅在 worker 和外层协程退出后进行带来源验证的深度清理。
- [取消协调器超时] → 保持 `cancelling`，不释放去重或暂存文件，返回可轮询的 `202`。
- [同名文件] → 绝不只按文件名删除，要求 task provenance 或文件哈希匹配。
- [服务重启] → 队列、重试和任务状态均拒绝 `cancelling`，删除请求可幂等继续收敛。
