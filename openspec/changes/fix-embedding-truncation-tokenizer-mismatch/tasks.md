## 1. 诊断与确认

- [x] 1.1 确认 tokenizer 不匹配：LightRAG o200k_base vs 千问 API ~2x 中文计数差异
- [x] 1.2 确认截断在逐条回退路径（`modalprocessors.py`）未覆盖

## 2. 字符级截断

- [x] 2.1 批量路径 `processor.py:_convert_to_lightrag_chunks_type_aware` 改为 `len(content) > 8000` 字符截断
- [x] 2.2 逐条路径 `modalprocessors.py:_create_entity_and_chunk` 新增字符级截断

## 3. 逐条容错嵌入

- [x] 3.1 `processor.py:_store_chunks_to_lightrag_storage_type_aware` 改为逐条 `upsert`，单条失败跳过并记 warning
- [x] 3.2 批量失败时记录 `N/M chunks skipped` 汇总日志

## 4. 超时保护

- [x] 4.1 `.env` 添加 `PROCESS_TIMEOUT=86400`，防止长时间处理被父进程杀死

## 5. 验证

- [x] 5.1 语法检查通过
- [x] 5.2 263 测试全部通过，无回归
- [ ] 5.3 上传含图片/表格文档，确认批量嵌入一次成功，不再降级逐条回退
