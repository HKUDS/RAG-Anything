## Why

当前智能体对话中的图片召回依赖检索上下文（ctx）中恰好包含带 `Image Path:` 行的 chunk。当向量/BM25 检索未能将图片 chunk 排入 top-15 时，唯一的兜底机制是 bigram 字符级全库扫描——这在 VLM 用英文描述中文文档图表的常见场景下命中率为零。此外，AgenticRAG（ReAct/CoT）路径和普通 RAG 路径的图片提取逻辑各自独立但都受限于同样的脆弱性。需要一种**模式无关、语义级别**的图片发现机制，保证无论使用哪种查询模式都能正确召回相关图片。

## What Changes

- 新增 `_discover_images_via_graph()` 函数，利用实体图谱中已存在的 `text_entity →[belongs_to]→ image_entity` 边，通过图谱遍历发现查询相关的图片
- 在图片提取链路中插入图谱发现层：`extract_image_paths(ctx)` → **图谱发现（新增）** → bigram 兜底（保留）
- 图谱发现同时回填关联 chunk 的文本到 LLM 上下文，提升回答质量
- AgenticRAG 路径（ReAct/CoT）的图片提取同样加入图谱发现层
- bigram 全库扫描保留作为最后防线

## Capabilities

### New Capabilities

- `graph-image-discovery`: 基于实体图谱的图片发现——利用 LightRAG 知识图谱中实体间的 `belongs_to` 关系，从查询匹配的文本实体遍历到关联的图片实体，提取图片路径并回填上下文，实现模式无关的语义级图片召回。

### Modified Capabilities

<!-- No existing specs need requirement changes — this is a new capability layered on top of existing retrieval. -->

## Impact

- 受影响文件：`raganything/routers/agent.py`（主要修改，新增函数 + 修改图片提取块）
- 无 API 变更、无数据库 schema 变更、无**BREAKING** 变更
- 依赖现有基础设施：`GraphRetriever.search_with_paths()`（已有）、实体图谱中的 `belongs_to` 边（多模态处理时已创建）
- 性能影响：仅在 `extract_image_paths(ctx)` 未找到图片时触发一次图谱查询，正常情况下零额外开销
