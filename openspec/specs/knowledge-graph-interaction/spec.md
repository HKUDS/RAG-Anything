## ADDED Requirements

### Requirement: Hover highlight
The system SHALL visually highlight a node and its connected edges when the user hovers over it.

#### Scenario: Node hover
- **WHEN** the user hovers the cursor over a node
- **THEN** the hovered node SHALL enlarge to 1.5× its normal radius
- **AND** all directly connected edges SHALL increase in opacity to 1.0 and stroke-width to 2.5
- **AND** all non-connected nodes and edges SHALL reduce opacity to 0.15
- **AND** a tooltip SHALL appear showing the node's full name and type label

#### Scenario: Hover exit
- **WHEN** the cursor leaves a node
- **THEN** all visual properties SHALL return to their default state
- **AND** the tooltip SHALL disappear

### Requirement: Drag visual feedback
The system SHALL provide visual feedback during node dragging operations.

#### Scenario: Drag start
- **WHEN** the user starts dragging a node
- **THEN** the dragged node SHALL increase to 1.3× its normal radius
- **AND** the node SHALL gain a drop-shadow effect (svg filter)
- **AND** the cursor SHALL change to `grabbing`

#### Scenario: Drag end cooldown
- **WHEN** the user releases a dragged node
- **THEN** the node SHALL snap back to normal size over 200ms
- **AND** the shadow effect SHALL be removed
- **AND** the simulation SHALL enter cooldown (alphaTarget set to 0)

### Requirement: Responsive container
The system SHALL adapt the SVG canvas size to its parent container dimensions.

#### Scenario: Container resize
- **WHEN** the parent container changes width (window resize, sidebar toggle, etc.)
- **THEN** the SVG SHALL update its width/height to match the container
- **AND** the force center SHALL be updated to the new midpoint
- **AND** a ResizeObserver SHALL be used to monitor container dimension changes

#### Scenario: Minimum height
- **WHEN** the viewport height is small
- **THEN** the SVG SHALL maintain a minimum height of 350px
- **AND** the graph SHALL remain fully interactive (scrollable if needed)

### Requirement: Edge labels
The system SHALL NOT render edge text labels on the KnowledgeGraphD3 component, as the legend already indicates line meaning for each relationship type.

#### Scenario: Edge labels are not rendered
- **WHEN** edges are rendered between nodes in KnowledgeGraphD3
- **THEN** no textPath or text elements SHALL be created for edge labels
- **AND** the legend (color swatches + line dash patterns) SHALL remain the sole source of relationship type information

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
