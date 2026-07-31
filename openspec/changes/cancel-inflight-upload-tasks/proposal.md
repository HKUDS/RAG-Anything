## Why

已提交的上传任务在开始处理后无法删除。只从前端显示删除按钮会留下运行中的 worker、重试任务或部分索引，导致已删除的文件重新出现或继续写入知识库。

## What Changes

- 允许有知识库写权限且可访问该知识库的上传者删除排队中、处理中和等待自动重试的上传任务。
- 为处理中和等待重试任务引入持久化的 `cancelling` 过渡状态，停止关联处理、阻止晚到回写，并在清理完成后标记为 `deleted`。
- 扩展上传抽屉：处理中和等待重试任务在确认后显示取消进度，直到服务端确认删除；排队任务保留即时删除体验。
- 保持已完成、失败和降级文档的现有文档删除流程，不放宽活跃文档删除的保护。

## Capabilities

### New Capabilities
- `inflight-upload-cancellation`: 对未完成上传任务提供可恢复、可轮询且按任务范围清理的取消删除生命周期。

### Modified Capabilities
- `upload-concurrency-control`: 上传队列必须识别 `cancelling`/`deleted` 任务并拒绝认领或重新入队。
- `background-task-lifecycle`: 文档处理 worker 在任务取消后不得写入完成、失败或自动重试状态。

## Impact

- 后端：`raganything/routers/knowledge.py`、`raganything/services/kb_service.py`、`raganything/services/state_service.py`、`raganything/services/upload_retry.py` 及 PostgreSQL 迁移。
- 前端：`frontend/src/pages/KnowledgeDetailPage.jsx` 的上传抽屉交互；复用现有删除 API。
- 测试：上传任务、重试恢复、任务状态和文档清理生命周期回归测试。
