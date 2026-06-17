## 1. LightRAG operate.py Chunk Fallback Patch

- [x] 1.1 在 `raganything/` 下创建 `lightrag_patches.py`，实现 `patch_chunk_resolution()` 函数
- [x] 1.2 在 `_find_related_text_unit_from_entities` 的 `get_by_ids` 返回全 None 时，注入单条 fallback 循环：遍历每个 chunk_id 调用 `get_by_id(chunk_id)` 单独取回
- [x] 1.3 在 `_find_related_text_unit_from_relations` 中同样注入单条 fallback
- [x] 1.4 在 `_merge_all_chunks` 中添加有效性预检：过滤 `content` 为空/缺失的 chunk 条目
- [x] 1.5 添加 chunk 解析统计日志：`Chunk resolution: {total} IDs, {success} resolved, {fail} not found`（INFO 级别）
- [x] 1.6 当 `fail > 0` 时，输出 WARNING 日志及最多 3 个失败 chunk ID 样本
- [x] 1.7 添加 patch 版本兼容性检测：在 import 时检查 lightrag 版本，不匹配时跳过并 WARNING

## 2. Context Building 降级告警

- [x] 2.1 在 `_build_context_str`（或 monkey-patch 中）检测 `merged_chunks=0` 且 `entities_context > 0` 时输出 `[CHUNK_DEGRADED]` WARNING 日志
- [x] 2.2 RAG-Anything 端：在 `query.py` 的 RRF 模式中，检测 chunks=0 时在 LLM prompt 追加降级提示
- [x] 2.3 RAG-Anything 端：在 `query.py` 的 graph 模式中，检测 chunks=0 时在 LLM prompt 追加降级提示
- [x] 2.4 `server.py` 端：在 `query_rag` 和 `agent_query_stream` 端点中，检测 chunks=0 时在响应/日志中标记降级

## 3. 根因诊断增强

- [x] 3.1 在 `_find_related_text_unit_from_entities` 中增加 DEBUG 日志：打印 entity `source_id` 解析出的 chunk ID 格式（前 5 个样本）
- [x] 3.2 在 `text_chunks_db.get_by_ids` 调用前后增加 DEBUG 日志：输入 key 和目标存储中存在的部分 key（前 5 个样本对比）
- [x] 3.3 输出对比日志帮助定位 `source_id` 中的 chunk ID 与 `text_chunks_db` 实际 key 之间的格式差异

## 4. 集成验证

- [ ] 4.1 重启服务后查询"系统包含哪些功能模块"，验证日志中出现 chunk 解析统计
- [ ] 4.2 验证 chunks=0 时 LLM prompt 中包含降级提示
- [ ] 4.3 验证正常查询路径（有 chunk 时）行为不变，回归测试通过
- [ ] 4.4 验证单条 fallback 能成功取回部分 chunk 数据（如有）
