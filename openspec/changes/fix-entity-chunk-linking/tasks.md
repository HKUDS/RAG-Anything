## 1. 实现实体→多模态 chunk 桥接 (processor.py)

- [ ] 1.1 新增 `_link_entities_to_multimodal_chunks()` 方法：接收多模态 chunk 列表和 entity_chunks 映射，扫描每个 chunk 内容中出现的实体名称（≥3 字符），收集 chunk_id → entity_names 映射
- [ ] 1.2 对每个匹配到的 (entity_name, chunk_id) 对，创建 `mentions` 边（`src=entity_name, tgt=chunk_id, weight=5.0, keywords="mentions,found_in"`）
- [ ] 1.3 将匹配到的 chunk_id 追加到实体的 `source_id` 字段，确保后续 `merge_nodes_and_edges()` 能识别新链接
- [ ] 1.4 在 `_process_multimodal_content_batch_type_aware()` 中调用（`_store_multimodal_main_entities()` 之后、`_batch_merge_lightrag_style_type_aware()` 之前）
- [ ] 1.5 添加 INFO 日志：记录本次处理建立了多少实体→chunk 链接

## 2. 验证

- [ ] 2.1 对已上传的"13.相关文件"使用 `force_reprocess=true` 重新处理，确认日志显示建立了实体→多模态 chunk 链接
- [ ] 2.2 查询"毕业答辩的地点"，确认 RRF 日志中 `graph-chunk` 出现在 top-15 上下文，且带 `[来源实体: 毕业设计答辩]` 标注
- [ ] 2.3 确认 LLM 回答返回 13216 而非 13220
- [ ] 2.4 确认通用查询不受影响
