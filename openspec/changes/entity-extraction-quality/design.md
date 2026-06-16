# Design: 实体抽取质量控制

## Context

当前实体抽取流程：

```
文档 → LightRAG.extract_entities() → 实体节点入库(chunk_entity_relation_graph)
                                          ↓
                                    关系边入库(chunk_entity_relation_graph)
                                          ↓
                                    entities_vdb + full_entities
```

关键发现：LightRAG **已经原生支持 `ENTITY_TYPES` 环境变量**（`lightrag.py:506-511`），通过 `addon_params` 传递给 `extract_entities()`（`operate.py:2905-2907`）。RAG-Anything 通过 `lightrag_kwargs` 可以覆盖 `addon_params`。连通性过滤需要在实体入库后实现，因为 LightRAG 没有内置此功能。

## Goals / Non-Goals

**Goals:**
- 通过 `ENTITY_TYPES` 环境变量配置实体类型白名单，利用 LightRAG 原生机制
- 通过 `ENTITY_EXTRACTION_MIN_DEGREE` 环境变量实现连通性过滤，移除孤立实体
- 在 `RAGAnythingConfig` 中增加配置字段，支持环境变量和代码配置
- 在服务器设置 API 和前端设置页面暴露配置
- 所有新配置默认关闭，完全向后兼容

**Non-Goals:**
- 不修改 LightRAG 源码
- 不实现基于 LLM 的实体置信度评估（成本高、收益低）
- 不实现基于向量相似度的实体过滤（此方案留待后续评估）
- 不修改前端设置页面以外的 UI

## Decisions

### Decision 1: 实体类型白名单 → 复用 LightRAG `ENTITY_TYPES` 环境变量

**方案**: 在 RAG-Anything 层透传 `ENTITY_TYPES` 到 LightRAG 的 `addon_params.entity_types`。

**理由**: LightRAG 已原生支持 `ENTITY_TYPES` 环境变量。RAG-Anything 只需：
1. 在 `RAGAnythingConfig` 中增加 `entity_types` 字段读取此环境变量
2. 在 `lightrag_kwargs` 中注入 `addon_params.entity_types`
3. 不需要修改 `extract_entities()` 调用链

**备选方案**: 在 RAG-Anything 的 prompt 中注入实体类型约束。但 LightRAG 的 `extract_entities()` 已将 `entity_types` 写入 prompt template（`operate.py:2905`），自建方案会导致重复和冲突。

### Decision 2: 连通性过滤 → 在 `processor.py` 实体入库后执行

**方案**: 在 `_batch_extract_entities_lightrag_style_type_aware()` 或 `_batch_add_belongs_to_relations_type_aware()` 之后，新增 `_filter_low_degree_entities()` 方法，读取所有实体节点的 degree，移除 degree < min_degree 的节点。

**流程**:
```
extract_entities() → 实体节点入库(chunk_entity_relation_graph)
                          ↓
                    关系边入库
                          ↓
                    _filter_low_degree_entities()  ← 新增步骤
                          ↓
                    移除 degree < min_degree 的节点
                    移除这些节点的 entities_vdb 条目
                    移除这些节点的 full_entities 条目
                          ↓
                    保留关联的 text_chunks（只移除实体，不移除文本）
```

**理由**: 必须等关系边入库后才能计算 degree。在 RAG-Anything 层做过滤而不是修改 LightRAG，保持兼容性。

**备选方案**: 在 `GraphRetriever._match_entities()` 中过滤（运行时过滤）。但这个方案只影响检索结果，不清理存储——孤实体仍占用向量库空间和图存储空间。

### Decision 3: 配置存储 → 环境变量 + `RAGAnythingConfig` 双通道

**方案**: 新增两个 `RAGAnythingConfig` 字段：
```python
entity_types: str = ""    # "Part,Assembly,Process"
entity_extraction_min_degree: int = 0  # 0=不过滤
```

通过 `get_env_value()` 从 `ENTITY_TYPES` 和 `ENTITY_EXTRACTION_MIN_DEGREE` 环境变量读取。

在 `_ensure_lightrag_initialized()` 中，将 `entity_types` 解析为列表后注入 `lightrag_kwargs["addon_params"]["entity_types"]`。

在 `parse_document()` 流程中（`processor.py`），实体入库后检查 `entity_extraction_min_degree > 0`，执行连通性过滤。

**理由**: 与现有 `RAGAnythingConfig` 模式一致。配置字段而非硬编码，支持代码级和部署级两种配置方式。

### Decision 4: 前端配置入口 → SettingsPage.jsx 新增控件

**方案**: 在设置页面"解析器"区域下方增加"实体抽取"配置卡片，包含：
- `entity_types`: 文本输入框（逗号分隔的实体类型列表）
- `entity_extraction_min_degree`: 数字输入框（最小连通度，0=不过滤）

**理由**: 保持与现有设置页面布局一致。实体类型需要领域知识手动配置，文本输入比下拉选择更灵活。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|---|---|
| 实体类型过严导致重要实体被过滤 | 默认使用 LightRAG 内置类型；白名单是可选功能，用户主动选择启用 |
| 连通性过滤阈值过高移除有用实体 | 默认 0（不过滤）；建议从 1 开始（只移除完全孤立的实体） |
| `ENTITY_TYPES` 已在 LightRAG 层面被读取，RAG-Anything 再配置可能导致冲突 | RAG-Anything 的 `lightrag_kwargs` 会覆盖 LightRAG 默认的 `addon_params`；当 RAG-Anything 配置了 `entity_types` 时优先使用；未配置时 LightRAG 自行读取环境变量 |
| 连通性过滤在每次文档处理时执行，增加处理时间 | 只在 `entity_extraction_min_degree > 0` 时执行；过滤是 O(n) 的图遍历操作，开销极小 |
