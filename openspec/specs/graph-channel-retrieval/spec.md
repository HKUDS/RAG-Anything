# Graph Channel Retrieval

## Purpose

为 RRF 三路融合检索提供知识图谱检索通道。通过实体匹配和邻居遍历在 LightRAG 知识图谱中发现关联文档，支持子图可视化数据输出。

## Requirements

### Requirement: 实体匹配检索

系统 SHALL 从用户查询中提取实体名称，在 LightRAG 知识图谱中匹配对应的实体节点，返回与匹配实体关联的文档 chunk。

#### Scenario: 精确实体匹配
- **WHEN** 查询包含 "张三" 且知识图谱中存在 "张三" 实体节点
- **THEN** 系统匹配到 "张三" 实体
- **THEN** 返回与该实体关联的所有文档 chunk

#### Scenario: 实体未匹配
- **WHEN** 查询中的实体在知识图谱中不存在
- **THEN** 图谱通道返回空结果列表
- **THEN** 不影响其他通道检索

### Requirement: 邻居遍历检索

系统 SHALL 从匹配到的实体节点出发，沿知识图谱边遍历 1-2 跳邻居节点，召回邻居实体关联的文档 chunk。

#### Scenario: 1 跳邻居遍历
- **WHEN** 匹配到实体 "张三" 且 `GRAPH_DEPTH=1`
- **THEN** 系统遍历 "张三" 的 1 跳邻居（如 "技术部"、"项目A"）
- **THEN** 返回 "张三" 及其 1 跳邻居关联的所有 chunk

#### Scenario: 2 跳邻居遍历
- **WHEN** 匹配到实体 "张三" 且 `GRAPH_DEPTH=2`
- **THEN** 系统遍历 "张三" 的 1 跳和 2 跳邻居
- **THEN** 2 跳邻居的 chunk 分数低于 1 跳邻居（按距离加权衰减）

### Requirement: 图谱检索候选限制

系统 SHALL 通过 `GRAPH_TOP_K`（默认 30）限制图谱通道返回的最大候选项数量，按实体匹配分数和距离加权排序。

#### Scenario: 候选数量限制
- **WHEN** 图谱遍历返回 100 个相关 chunk 且 `GRAPH_TOP_K=30`
- **THEN** 系统只返回距离加权分数最高的 30 个 chunk

#### Scenario: 结果不足 top_k
- **WHEN** 图谱遍历仅返回 5 个相关 chunk
- **THEN** 系统返回全部 5 个结果

### Requirement: 图谱可视化数据

系统 SHALL 提供 `get_subgraph_visualization(entity_ids)` 方法，返回指定实体的子图数据（nodes + edges），供前端 D3 力导向图渲染。

#### Scenario: 获取子图数据
- **WHEN** 调用 `HybridSearchEngine.get_subgraph(query_entities)`
- **THEN** 返回 `{nodes: [...], edges: [...]}` 格式的 JSON 数据
- **THEN** nodes 包含实体名称、类型、chunk_count
- **THEN** edges 包含源实体、目标实体、关系类型

### Requirement: 图谱配置

系统 SHALL 通过环境变量 `GRAPH_DEPTH`（默认 2）控制邻居遍历深度，`GRAPH_TOP_K`（默认 30）控制返回候选项数量。

#### Scenario: 自定义遍历深度
- **WHEN** `GRAPH_DEPTH=1`
- **THEN** 图谱检索仅遍历 1 跳邻居
- **WHEN** `GRAPH_DEPTH=3`
- **THEN** 图谱检索遍历 1-3 跳邻居，但 3 跳以上 chunk 权重显著降低
