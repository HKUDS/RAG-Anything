## Why

知识库页面统计数据与实际数据严重不符：实体 434 条但分块仅显示 3 个，实体与关系数量也存在偏差。根因是后端 stats API 和 graph API 使用了错误的聚合方式或硬编码限制，导致前端展示失真。用户无法通过页面获得准确的知识库状态。

## What Changes

- **修复 chunk 统计来源**：stats API 的 `chunks` 字段从 `len(vdb_chunks.json)` 改为汇总 `kv_store_doc_status.json` 中各文档的 `chunks_count`，因为 `vdb_chunks.json` 是 LightRAG 向量数据库内部存储文件，其 JSON 键数不代表实际分块数量
- **移除 graph API 硬编码截断**：`/knowledge/graph` 端点中 `entity_names[:40]`、`relation_pairs[:100]`、`nodes[:120]`、`edges[:80]` 等硬限制导致图谱数据不完整，改为返回全量数据（前端已有 D3 力导向图渲染策略控制显示量）
- **统一 stats 数据来源**：确保实体数、关系数、分块数均从 LightRAG 持久化存储文件正确聚合

## Capabilities

### New Capabilities
<!-- No new capabilities — this is a bug fix for existing stats/graph display -->

### Modified Capabilities
<!-- No spec-level requirement changes — existing API contracts preserved, only fixing data aggregation logic -->

## Impact

- **Affected files**:
  - `raganything/routers/knowledge.py` — `knowledge_stats()` (line 322) 和 `graph_data()` (line 407)
- **API compatibility**: 响应字段名不变（`documents`, `entities`, `relations`, `chunks`），仅修正数值
- **Frontend**: 无需改动，统计卡片和知识图谱自动展示修正后的数据
- **Upload worker**: 不受影响，仅改了读取/聚合侧的逻辑
