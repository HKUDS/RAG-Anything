## ADDED Requirements

### Requirement: Search empty state
知识图谱搜索过滤无结果时，系统 SHALL 显示明确的空状态提示而非空白画布。

#### Scenario: Search returns no results
- **WHEN** 用户输入搜索词后 `displayNodes` 为空且 `graphSearch` 非空
- **THEN** 系统 SHALL 在 SVG 区域显示半透明遮罩层
- **AND** 遮罩层 SHALL 包含文字"无匹配实体"
- **AND** 遮罩层 SHALL 包含"清除搜索"按钮，点击后清空搜索词并恢复图谱

#### Scenario: Clear search restores graph
- **WHEN** 用户点击"清除搜索"按钮
- **THEN** 搜索输入框 SHALL 清空
- **AND** 图谱 SHALL 恢复到搜索结果前的状态

### Requirement: Search neighbor expansion
搜索时系统 SHALL 自动展开匹配节点的直接邻居，确保搜索结果有上下文关系。

#### Scenario: Search includes direct neighbors
- **WHEN** 用户输入搜索词后存在匹配节点
- **THEN** 显示列表 SHALL 包含所有名称匹配的节点
- **AND** 显示列表 SHALL 额外包含匹配节点的所有直接邻居（双向连接）

#### Scenario: Neighbor is also a match
- **WHEN** 某个邻居节点本身也匹配搜索词
- **THEN** 该节点 SHALL 仅出现一次（不去重添加）

### Requirement: Node count limit with notice
系统 SHALL 对显示节点数量应用统一上限，并在截断时告知用户。

#### Scenario: Node limit applied without search
- **WHEN** 图谱节点总数超过 100 且用户未使用搜索
- **THEN** 系统 SHALL 仅渲染前 100 个节点
- **AND** 图形下方 SHALL 显示 "显示 100/N 个节点" 提示（N 为实际总数）

#### Scenario: Node limit applied with search
- **WHEN** 搜索匹配节点 + 邻居总数超过 100
- **THEN** 系统 SHALL 仅渲染前 100 个节点
- **AND** 图形下方 SHALL 显示截断提示

#### Scenario: Node count below limit
- **WHEN** 显示节点数未超过 100
- **THEN** 系统 SHALL 渲染所有节点
- **AND** 不显示截断提示
