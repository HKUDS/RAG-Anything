## Why

文档处理中文本实体抽取和多模态内容（表格、图片）处理是两条独立管线。文本中提取的实体（如"毕业设计答辩"）通过 `source_id` 链接到文本 chunk，但**不会自动链接到包含同名数据的多模态 chunk**（如表 chunk 中的地点数据）。这导致图谱检索时从实体出发的 BFS 遍历无法到达包含关键数据的多模态 chunk，图谱通道在 RRF 融合中完全失效（已确认：`RRF graph-chunks: NONE in top-15 context`）。

## What Changes

- **处理时实体回链**（`processor.py`）：在多模态处理完成后，扫描所有多模态 chunk 内容，检测其中出现的已存在实体名称，将对应 chunk_id 追加到实体的 `source_id` 列表。确保文本实体也能链接到包含其数据的多模态 chunk
- **图谱边补充**：当多模态 chunk 中检测到实体名称时，创建 `mentions` 边（`实体 → chunk`），确保图谱检索的 BFS 遍历能到达多模态 chunk
- **保留查询时标注**（`query.py`）：保留 `fix-entity-disambiguation` 中已实现的全 chunk 实体扫描标注作为纵深防御

## Capabilities

### New Capabilities
- `entity-multimodal-linking`: 实体多模态链接 — 文档处理完成后自动将文本实体链接到包含其实体名称的多模态 chunk（表格、图片），确保图谱检索能发现多模态 chunk 中的实体属性数据

### Modified Capabilities
<!-- No existing specs cover this processing behavior -->

## Impact

- **文件**: `raganything/processor.py` — 多模态处理完成后增加实体名称扫描和 chunk 链接逻辑（`_process_multimodal_content_batch_type_aware()` 和 `_store_multimodal_main_entities()` 之后）
- **文件**: `raganything/query.py` — 保留（不删除）全 chunk 实体扫描标注作为防御
- **数据影响**: 已处理文档需重新处理才能建立新链接（可选 `force_reprocess`）
- **性能影响**: 文档处理时增加一次 O(实体数 × 多模态 chunk 数) 的扫描，通常在毫秒级
