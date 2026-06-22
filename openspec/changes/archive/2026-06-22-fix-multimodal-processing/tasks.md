## 1. 修复多模态默认值（multimodal-default-fix）

- [x] 1.1 修改 `kb_service.py` `create_rag()` 中 `enable_image_processing` 的 fallback 从 `"false"` 改为 `"true"`
- [x] 1.2 修改 `kb_service.py` `create_rag()` 中 `enable_table_processing` 的 fallback 从 `"false"` 改为 `"true"`
- [x] 1.3 修改 `kb_service.py` `create_rag()` 中 `enable_equation_processing` 的 fallback 从 `"false"` 改为 `"true"`

## 2. 设置页变更时重建 KB 实例（multimodal-settings-rebuild）

- [x] 2.1 修改 `admin.py` `update_settings`，当 `enable_image` 变更时设置 `need_rebuild = True`
- [x] 2.2 修改 `admin.py` `update_settings`，当 `enable_table` 变更时设置 `need_rebuild = True`
- [x] 2.3 修改 `admin.py` `update_settings`，当 `enable_equation` 变更时设置 `need_rebuild = True`
- [x] 2.4 修改 `admin.py` `update_settings`，当 `enable_video` 变更时设置 `need_rebuild = True`

## 3. 回溯处理 API 端点（multimodal-retroactive-processing）

- [x] 3.1 在 `raganything/services/kb_service.py` 中新增 `_reprocess_multimodal_for_kb()` 后台任务函数：扫描 doc_status 中 `multimodal_processed != true` 的文档，定位原始文件，重新解析并仅执行多模态处理
- [x] 3.2 在 `raganything/routers/knowledge.py` 中新增 `POST /api/kb/{kb_name}/reprocess-multimodal` 端点，接收请求并调度后台任务
- [x] 3.3 端点返回排队文档数，后台通过 WebSocket 推送进度

## 4. 验证

- [x] 4.1 重启服务，验证新创建 KB 默认启用图片/表格/公式处理
- [x] 4.2 在设置页关闭图片处理，验证 KB 实例被清除、新请求以关闭状态重建
- [x] 4.3 调用回溯 API 对已有 KB 执行多模态回溯，验证文档 `multimodal_processed` 变为 `true`
  - 额外修复：`_reprocess_multimodal_for_kb()` 新增 parse cache 直接读取（bypass parser 变更导致 cache key 不匹配）
  - 缓存命中 → 内容分离 77 项 → VLM 77/77 chunk → 实体提取 → 实体合并 (728 entities) → 关系处理 (1855 rels) 🔄
- [x] 4.4 验证回溯后查询能返回图片相关信息
