## Why

上传单个文档后，文档列表出现两个条目：一个是带随机 hash 前缀的历史处理记录（状态为"已完成"），另一个是当前上传任务（状态为"处理中"）。这是因为文件命名在 `processing_tasks`（存原始文件名）和 `kv_store_doc_status.json`（存 hash 前缀文件名）之间不一致，导致 `list_documents` 去重失效。同时，`processing_tasks` 中的已完成条目从未被清理，`doc_status` 中的旧记录也永久累积。

## What Changes

- **修复 list_documents 文件名去重逻辑**：从 hash 前缀文件名中提取原始文件名，使 `processing_tasks` 和 `kv_store_doc_status` 的去重比较使用统一的文件名格式
- **添加 hash 前缀剥离辅助函数**：识别并剥离 `8hex_` 前缀模式（如 `593dbd4b_测试.docx` → `测试.docx`）
- **清理已完成任务的 processing_tasks 条目**：在 `list_documents` 返回前或后台任务完成时移除已完成条目
- **定期清理 doc_status 旧条目**：同名文档重复上传时，移除旧的 doc_status 记录

## Capabilities

### New Capabilities

- `document-list-deduplication`: 文档列表去重逻辑，确保同一逻辑文档在列表中只出现一次，同时清理过期和重复的文档状态记录

### Modified Capabilities

<!-- No existing specs have requirement-level changes -->

## Impact

- **后端 API**：`raganything/routers/knowledge.py` — `list_documents` 端点去重逻辑修改
- **后端服务**：`raganything/services/state_service.py` — `cleanup_completed_tasks()` 接入调用链
- **配置/启动**：`server.py` — 启动事件中添加已完成任务清理
- **前端**：无需修改（`frontend/src/pages/KnowledgePage.jsx` 仅展示 API 返回数据，去重在后端完成）
