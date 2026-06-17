## Why

知识图谱检索中的实体匹配采用纯子串匹配（`graph_rag.py:_match_entities()`），当文档中存在名称相似的实体时（如"开题答辩"和"毕业设计答辩"），查询中任一关键词会同时命中两个实体，导致图谱通道返回混合上下文。LLM 收到混淆的检索内容后无法区分"13220（开题答辩地点）"和"13216（毕业设计答辩地点）"，持续给出错误答案。用户已验证该问题：多次询问毕业设计答辩地点，智能体始终返回开题答辩的地点 13220。

## What Changes

- **图谱实体匹配增强**：`GraphRetriever._match_entities()` 从纯子串匹配升级为基于 token 重叠度的加权匹配。查询词 token 与实体名称 token 重叠数越多的实体得分越高，特定度更高的实体（如"毕业设计答辩"匹配查询"毕业设计答辩地点"）排名优于通用实体（如"开题答辩"仅匹配"答辩"）
- **检索上下文标注实体来源**：图谱通道检索返回的 chunk 标注其来源实体名称（如 `[来源实体: 毕业设计答辩]`），使 LLM 能够将事实与具体实体关联
- **RAG 提示词增强**：在 RAG 查询提示中增加实体消歧指令——当检索内容包含多个相似实体时，LLM 必须区分并引用具体实体名称，不得将不同实体的属性混淆

## Capabilities

### New Capabilities
- `entity-disambiguation`: 实体消歧检索 —— 图谱检索中的实体匹配支持基于 token 重叠度的加权评分，确保特定度更高的实体优先匹配；检索上下文包含实体来源标注；LLM 提示词包含实体区分指令

### Modified Capabilities
<!-- No existing specs cover entity disambiguation -->

## Impact

- **文件**: `raganything/graph_rag.py` — `_match_entities()` 方法（第 98–141 行）改为加权匹配
- **文件**: `raganything/query.py` — `_aquery_rrf()` 中图谱通道结果上下文构建（约第 581–587 行），增加实体来源标注
- **文件**: `server.py` — RAG 查询提示词（第 2232–2244 行、第 2507–2517 行），增加实体消歧指令
- **文件**: `raganything/hybrid_search.py` — 图谱搜索结果传递实体名称信息（如需）
- **无新增依赖**，不改变 API 接口
