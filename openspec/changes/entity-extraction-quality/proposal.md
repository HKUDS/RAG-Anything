## Why

当前实体抽取完全委托给 LightRAG 内置的 `extract_entities()`，使用通用实体类型（Person, Organization, Location, Event, Concept 等）。在领域知识库场景（制造、工程、法律等），通用实体类型会产生大量噪音实体——LLM 将"12"抽为 Data、"304"抽为 Data、"M6"抽为 Artifact——这些低质量实体污染知识图谱，直接导致图谱通道检索结果包含无关 chunk。同时，LightRAG 不返回实体置信度分数，无法在事后过滤低质量实体。需要在抽取前（实体类型白名单约束）和抽取后（连通性过滤移除孤立实体）两个阶段实施质量控制。

## What Changes

- 新增 `entity_types` 配置项，通过 LightRAG 的 `addon_params` 注入领域实体类型白名单，约束 LLM 只抽取指定类型的实体
- 新增 `entity_extraction_min_degree` 配置项，在实体入库后自动移除 degree=0 的孤立实体（被抽取但未建立任何关系的实体）
- 在 `RAGAnythingConfig` 中增加上述两个配置字段，支持环境变量覆盖
- 在服务器 `GET/PUT /api/settings` 中暴露配置，前端设置页面增加对应 UI 控件
- 默认行为不变：未配置时保持 LightRAG 内置默认实体类型，不做连通性过滤

## Capabilities

### New Capabilities
- `entity-extraction-config`: 实体抽取质量控制 — 实体类型白名单 + 连通性过滤，通过配置和环境变量控制，不影响默认行为

### Modified Capabilities
- `graph-channel-retrieval`: 图谱通道检索质量受实体质量控制影响——更干净的实体 → 更精准的图谱邻居遍历 → 更相关的 chunk 返回

## Impact

- 影响代码：`raganything/config.py`（新增字段）、`raganything/processor.py`（实体入库后连通性过滤）、`raganything/raganything.py`（addon_params 传递）、`server.py`（设置 API）、`frontend/src/pages/SettingsPage.jsx`（设置 UI）
- 依赖：无新增依赖，复用 LightRAG 现有 `addon_params` 机制
- 兼容性：完全向后兼容，所有新配置项默认关闭/保持 LightRAG 默认值
