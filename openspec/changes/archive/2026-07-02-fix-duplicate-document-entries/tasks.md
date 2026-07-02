## 1. 添加 hash 前缀剥离辅助函数

- [x] 1.1 在 `raganything/routers/knowledge.py` 中添加 `_strip_hash_prefix(filename: str) -> str` 函数：使用 `re.match(r'^[0-9a-f]{8}_(.+)$', filename)` 剥离 8 位 hex 前缀，无匹配则原样返回

## 2. 修复 list_documents 去重逻辑

- [x] 2.1 修改 `list_documents` 中 `seen_files` 的填充逻辑：对 `info.get("file_path", "")` 先调用 `_strip_hash_prefix` 再存入 `seen_files`
- [x] 2.2 修改 `list_documents` 中合并 `processing_tasks` 的去重检查：对 `fn` 也调用 `_strip_hash_prefix`，与已剥离后的 `seen_files` 比较
- [x] 2.3 对 `doc_status` 来源的条目，同一原始文件名的多个条目只保留 `updated_at` 最新的那条

## 3. 清理已完成任务

- [x] 3.1 在 `list_documents` 函数开头（构建响应前）调用 `cleanup_completed_tasks()` 清理已完成/失败的任务
- [x] 3.2 从 `raganything/services/state_service.py` 导入 `cleanup_completed_tasks` 到 `knowledge.py` 路由模块

## 4. 验证

- [x] 4.1 检查 `cleanup_completed_tasks` 的 1 小时窗口限制是否合理——对于文档上传场景，任务完成即可清理，已移除时间限制
- [x] 4.2 验证批量上传（`upload_files`）是否也有相同问题——确认批量上传使用原始文件名无 hash 前缀，不受此 bug 影响（但有独立的磁盘覆盖风险，不在本次修复范围）
