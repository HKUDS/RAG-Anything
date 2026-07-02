## Context

RRF 检索返回的 chunk 中包含文档解析时提取的图片路径。当前这些图片信息在查询结果中被丢弃。服务器端已有 `extract_image_paths()` 工具函数可以从文本中提取图片路径。需要在 RRF 查询管线中利用这些已有能力，将 Top-3 相关图片附加到查询结果中。

## Goals / Non-Goals

**Goals:**
- RRF 检索后自动提取 chunk 中的图片路径，按 RRF 分数排序取 Top-3
- 图片以 base64 编码返回，前端可直接渲染
- 保持向后兼容：`only_need_context=True` 时图片作为额外字段返回

**Non-Goals:**
- 不做全库图片扫描（仅在 RRF 检索到的 chunk 中提取）
- 不做图片内容分析/VLM 描述（已有功能，不重复）
- 不修改非 RRF 模式（hybrid/local/global/naive 由 LightRAG 内部处理）

## Decisions

### Decision 1: 图片提取时机

**选择**: 在 `HybridSearchEngine.search()` 返回 chunk 后，在 `_aquery_rrf` 中提取图片。

**理由**: 图片提取依赖 RRF 排序结果（取分最高的 chunk 中的图片），属于查询层的逻辑，不应放在检索引擎中。

### Decision 2: 图片排序策略

**选择**: 按 chunk 的 RRF 分数降序排列，同一 chunk 内的图片按出现顺序排列，去重后取前 3 张。

**理由**: RRF 分数反映了 chunk 与查询的综合相关性，高分数 chunk 中的图片更可能相关。

### Decision 3: 返回格式

**选择**: `_aquery_rrf` 返回 `{"text": str, "images": List[dict]}` 字典。image dict: `{base64, path, source_chunk_id, rrf_score}`。

**理由**: 结构化返回便于前端分别渲染文本和图片。图片附带溯源信息有助于调试。
