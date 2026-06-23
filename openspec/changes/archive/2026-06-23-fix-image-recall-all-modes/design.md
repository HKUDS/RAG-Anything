## Context

当前图片召回链路为两段式：`extract_image_paths(ctx)` 从检索上下文提取 → bigram 全库扫描兜底。第一段依赖检索质量（图片 chunk 需排入 top-15），第二段是字符级匹配（中英混合场景命中率为零）。

实体图谱中已存在关键基础设施：
- 多模态处理时，从图片 chunk 提取的每个文本实体都创建了 `belongs_to` 边连接到图片实体（`base.py:503-538`）
- `GraphRetriever.search_with_paths()` 已实现实体匹配 + BFS 邻居遍历 + 带路径的 chunk 排序
- 图片实体类型为 `entity_type: "image"`，可通过遍历路径识别

本次设计在现有两段之间插入第三段：**基于实体图谱的图片发现**。

## Goals / Non-Goals

**Goals:**
- 所有查询模式（rrf/graph/hybrid/local/global/naive/mix）都能通过图谱发现相关图片
- 解决 bigram 兜底在中英混合内容中命中率为零的问题
- 发现图片的同时回填关联文本到 LLM 上下文
- AgenticRAG（ReAct/CoT）路径同样受益
- 零额外开销：仅在 `extract_image_paths(ctx)` 未找到图片时触发

**Non-Goals:**
- 不修改检索算法本身
- 不改变 LightRAG 内部逻辑
- 不修改数据库 schema
- 不新增外部依赖

## Decisions

### 决策 1：使用实体图谱遍历而非 embedding 相似度搜索

**选择**：`GraphRetriever.search_with_paths()` 实体遍历
**备选**：对 query 做 embedding → 在 chunks_vdb 中搜索 → 过滤含 `Image Path:` 的 chunk

**理由**：
- 图谱方案利用的是**符号化的实体关系**（`belongs_to` 边），不受语言差异影响——中文查询匹配到中文实体名，直接沿边找到英文描述的图片实体
- embedding 方案受限于 VLM 用英文描述中文图表时的语义 gap，这正是我们要解决的问题
- 图谱遍历已有完整实现（`_match_entities` + `_traverse_neighbors`），只需调用现有接口
- 图谱遍历是 O(匹配实体数 × 深度)，远小于 bigram 的 O(全库 chunk 数)

### 决策 2：在三段式链路中作为中间层

**选择**：`extract_image_paths(ctx)` → 图谱发现 → bigram 兜底
**备选**：替换 bigram 兜底、并行执行

**理由**：
- `extract_image_paths(ctx)` 是最直接的路径（ctx 中已有图片 chunk），几乎零开销，必须保留为第一道
- bigram 兜底保留作为最后防线——某些边缘情况下图谱可能没有覆盖（如纯图片文档无文本实体）
- 图谱发现是语义级别的，应在字符级 bigram 之前执行
- 并行执行增加复杂度但收益有限——前一道命中后后续不会执行

### 决策 3：函数放在 agent.py 中，不抽到独立模块

**选择**：`_discover_images_via_graph()` 作为 agent.py 的模块级异步函数
**备选**：放在 `query/pipeline.py` 或新建 `query/image_discovery.py`

**理由**：
- 该函数同时服务于普通 RAG 路径和 AgenticRAG 路径，两者都在 agent.py 中
- 函数依赖 `extract_image_paths`（定义在 shared.py，agent.py 已导入）和 `GraphRetriever`（通过 HybridSearchEngine 访问）
- 当前只有 agent.py 的查询流需要这个功能，暂不扩展到其他入口
- 如果未来 `query/pipeline.py` 的 `aquery()` 也需要，可以届时抽离

### 决策 4：同时回填文本到 ctx

**选择**：发现的图片关联 chunk 的文本内容追加到 ctx 尾部
**理由**：
- LLM 回答时能引用图片周围的文字描述，即使图片本身不被 VLM 分析
- 去重逻辑避免回填 ctx 中已有的内容（前 80 字符匹配）
- 限制回填 5 个 chunk，每个 1500 字符，控制 token 开销

## Risks / Trade-offs

- **[风险] 图谱尚未完全构建** → 新上传文档的实体提取可能尚未完成 → **缓解**：该函数仅在 `extract_image_paths(ctx)` 未找到图片时触发，此时已有检索结果；且 bigram 兜底仍在最后
- **[风险] 图谱遍历性能** → 大规模知识图谱 BFS 可能耗时 → **缓解**：`GraphRetriever` 已有限制深度（默认 2 跳）和 top-k；实测通常在 100ms 内完成
- **[取舍] 依赖 `belongs_to` 边的质量** → 如果实体提取质量差，边可能缺失 → **可接受**：这不是新问题，文本检索同样依赖实体提取质量
- **[取舍] 仅覆盖 agent 查询路径** → `query/pipeline.py` 的直接 `aquery()` 调用不受益 → **可接受**：直接 API 调用有 VLM 增强路径作为替代

## Migration Plan

1. 部署：新增代码，无配置变更，无数据迁移
2. 回滚：删除新增函数 + 还原 agent.py 图片提取块即可
3. 验证：上传含图表的文档 → 用不同查询模式提问 → 确认图片返回

## Open Questions

<!-- None — all decisions resolved -->
