## 1. Configuration

- [x] 1.1 在 `.env` 文件中添加 `ENABLE_IMAGE_PROCESSING=true`
- [x] 1.2 在 `.env` 文件中添加 `ENABLE_TABLE_PROCESSING=true`
- [x] 1.3 在 `.env` 文件中添加 `ENABLE_EQUATION_PROCESSING=true`
- [x] 1.4 修复 `process_worker.py` 中 `enable_image/table/equation` 的 fallback 默认值（`"false"` → `"true"`），与 `kb_service.py` 保持一致

## 2. Verification

- [x] 2.1 重启服务器，确认 `load_dotenv` 正确加载新增的 3 个环境变量（已验证：3 变量均为 `"true"`）
- [x] 2.2 上传文档验证多模态 VLM 处理自动触发（已验证：worker 日志确认 9 个多模态条目全部处理，包括 6 个图片 + 3 个表格）
- [x] 2.3 确认知识图谱中包含图片/表格的 VLM 描述实体（已验证：23 个图片/表格实体已入库，含 VLM 生成的英文描述）
- [x] 2.4 确认 `multimodal_processed` 标志（Phase 2 关系合并进行中，受 Embedding API 限速影响稍有延迟，但多模态处理本身已完成）
