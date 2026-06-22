## Why

用户上传 docx/pdf 等含图文档后，知识库只能检索到文本内容，图片相关数据完全缺失。根因：(1) `kb_service.py` 在创建 RAGAnything 实例时将 `enable_image_processing` 等三个多模态开关硬编码默认 `"false"`，与 `config.py` 的 dataclass 默认 `True` 矛盾；(2) 设置页面开启多模态开关后，不会重建已有 KB 实例，导致已创建的 KB 永远缺失多模态处理器；(3) 已在库中的文档无法回溯处理。

## What Changes

- **修复默认值不一致**：`kb_service.py` 中 `enable_image_processing`/`enable_table_processing`/`enable_equation_processing` 的 fallback 默认值从 `"false"` 改为 `"true"`，与 `config.py` 统一
- **设置页变更时重建 KB 实例**：`admin.py` 的 `update_settings` 在多模态开关变更时，清除已缓存的 KB 实例，使下次访问时以新配置重建
- **已有文档回溯处理**：新增 API 端点 `/api/kb/{kb_name}/reprocess-multimodal`，扫描 KB 中 `multimodal_processed != true` 的文档，从解析缓存中恢复 `content_list`，仅重新执行多模态处理（VLM 描述 + 实体入库），不重新上传文件、不重新插入文本

## Capabilities

### New Capabilities
- `multimodal-default-fix`: 多模态处理（图片/表格/公式）默认开启，`kb_service.py` 与 `config.py` 默认值统一为 `true`
- `multimodal-settings-rebuild`: 设置页切换多模态开关时，清除已缓存 KB 实例，确保新配置在下次访问时生效
- `multimodal-retroactive-processing`: 对 KB 中已入库但未完成多模态处理的文档，支持回溯触发 VLM 描述生成和实体提取

### Modified Capabilities
<!-- None — all capabilities are new -->

## Impact

| 层面 | 影响 |
|------|------|
| `raganything/services/kb_service.py` | 修改 `create_rag()` 中三个 `enable_*_processing` 的默认 fallback |
| `raganything/routers/admin.py` | 修改 `update_settings`，多模态开关变更加入 `need_rebuild` 条件 |
| `raganything/routers/knowledge.py` | 新增 `POST /api/kb/{kb_name}/reprocess-multimodal` 端点 |
| `raganything/processor/doc_processor.py` | 已有 `_process_multimodal_content` / `_process_multimodal_content_background` 可复用，无需修改 |
| `raganything/raganything.py` | 无需修改——处理器注册逻辑已按 config 正确工作 |
| `.env` | 建议添加 `ENABLE_IMAGE_PROCESSING=true` 等为显式默认 |
