## Context

知识库页面（KnowledgePage）通过 `/api/knowledge/stats` 和 `/api/knowledge/graph` 获取统计数据与图谱数据。当前实现存在两个数据聚合缺陷：

1. **Chunk 统计错误**：stats API 使用 `len(vdb_chunks.json)` 作为 chunk 总数。`vdb_chunks.json` 是 LightRAG NanoVectorDB 的内部存储文件，其 JSON 结构键值不代表 1:1 映射到实际分块数。实际分块数应汇总自 `kv_store_doc_status.json` 中各文档的 `chunks_count`。

2. **Graph 数据截断**：graph API 在多个层级施加硬编码限制——`entity_names[:40]`（每个实体条目最多40个名称）、`relation_pairs[:100]`（每个关系条目最多100对）、`nodes[:120]`、`edges[:80]`。这些限制导致图谱数据严重不完整，影响前端可视化。

## Goals / Non-Goals

**Goals:**
- 修复 `/knowledge/stats` 的 `chunks` 字段，使其从 `doc_status` 聚合真实分块数
- 移除 `/knowledge/graph` 的多层硬编码截断，返回全量图谱数据
- 不改变 API 响应格式（字段名保持不变）
- 不影响文档上传 worker（`process_worker.py`）和文档处理流程

**Non-Goals:**
- 不重构 stats/graph 存储架构
- 不修改前端页面代码
- 不改变 LightRAG 内部存储逻辑
- 不处理实体/关系本身的准确性（那是 NLP 抽取质量的问题）

## Decisions

### Decision 1: Chunk 计数改用 `doc_status` 聚合

**选择**：从 `kv_store_doc_status.json` 遍历所有文档条目，累加 `chunks_count`。

**替代方案**：
- ❌ 修复 `vdb_chunks.json` 使其键数等于真实 chunk 数 — 这是 LightRAG 内部实现，修改风险高且可能影响向量检索
- ❌ 从 LightRAG 实例的 `chunks_vdb` 读取 — 需要初始化完整 RAGAnything 实例，性能开销大
- ✅ **选用方案**：直接从已持久化的 `doc_status` JSON 聚合，性能最优且数据准确

### Decision 2: Graph 端点移除硬编码截断

**选择**：移除 `[:40]`、`[:100]`、`[:120]`、`[:80]` 限制，返回全量节点和边。

**替代方案**：
- ❌ 将限制改为更大的值（如 500、1000）—— 治标不治本
- ❌ 添加分页参数 —— 引入不必要的 API 复杂度
- ✅ **选用方案**：直接移除限制，前端已有的 D3 力导向图在非搜索模式下仅渲染前 60 个节点（`displayNodes.slice(0, 60)`），性能瓶颈在前端而非后端数据量

### Decision 3: 最小改动原则

仅修改 `knowledge.py` 中两个端点的聚合逻辑。不触及 `kb_service.py`、`process_worker.py`、`doc_processor.py` 等文件。符合 Minimal Change Engineer 原则。

## Risks / Trade-offs

- **Graph 全量返回可能产生大响应体**：如果知识库有 10000+ 实体和 50000+ 关系，JSON 响应可能超过几 MB。但当前项目规模下（434 实体、200 关系），响应体在可接受范围。远期可考虑添加可选的分页参数。
- **`doc_status` 可能不存在或损坏**：已有的 `_safe_load_json` 函数处理了 JSON 损坏场景，返回空 dict，stats 将显示 0，不会崩溃。

## Migration Plan

无需迁移。部署后刷新知识库页面即可看到修正数据。API 响应格式不变，前端无需更新。
