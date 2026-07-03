## MODIFIED Requirements

### Requirement: Edge labels
The system SHALL NOT render edge text labels on the KnowledgeGraphD3 component, as the legend already indicates line meaning for each relationship type.

#### Scenario: Edge labels are not rendered
- **WHEN** edges are rendered between nodes in KnowledgeGraphD3
- **THEN** no textPath or text elements SHALL be created for edge labels
- **AND** the legend (color swatches + line dash patterns) SHALL remain the sole source of relationship type information

## ADDED Requirements

### Requirement: Search neighbor highlight in KnowledgeGraphD3
KnowledgeGraphD3 搜索时系统 SHALL 自动包含匹配节点的直接邻居。

#### Scenario: Search expands to neighbors
- **WHEN** 用户在 KnowledgeGraphD3 中输入搜索词后存在匹配节点
- **THEN** 过滤后的节点列表 SHALL 包含名称匹配的节点
- **AND** 过滤后的节点列表 SHALL 包含匹配节点的所有直接邻居（双向）
- **AND** 边列表 SHALL 仅保留两端均在过滤节点集中的边

### Requirement: Edge deletion resets sidebar
删除图谱关系后，KnowledgeDetailPage 的实体详情侧边栏 SHALL 清空选中状态并回退到实体列表。

#### Scenario: Edge deletion clears selection
- **WHEN** 用户从侧边栏删除一条关系
- **AND** 删除操作成功
- **THEN** `selectedNode` 状态 SHALL 设为 null
- **AND** `nodeDetails` 状态 SHALL 设为 null
- **AND** `graphNodeDetail` 状态 SHALL 设为 null
- **AND** 侧边栏 SHALL 显示全部实体列表
