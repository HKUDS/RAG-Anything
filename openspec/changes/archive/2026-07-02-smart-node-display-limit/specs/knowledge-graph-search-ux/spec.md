## MODIFIED Requirements

### Requirement: Node count limit with notice
系统 SHALL 对无搜索场景下的图谱节点按连接度降序排列，优先显示核心结构节点。用户 SHALL 可一键切换为全量渲染。

#### Scenario: Node limit applied without search
- **WHEN** 图谱节点总数超过 200 且用户未使用搜索
- **THEN** 系统 SHALL 按节点连接度（degree）降序排列
- **AND** 系统 SHALL 渲染前 200 个节点
- **AND** 图形下方 SHALL 显示 "显示 200/N 个节点" 提示和"展示全部"按钮

#### Scenario: User requests full view
- **WHEN** 用户点击"展示全部"按钮
- **THEN** 系统 SHALL 渲染所有节点（无数量限制）
- **AND** 若节点数超过 500，按钮旁 SHALL 显示性能警告文本

#### Scenario: Node count below limit
- **WHEN** 显示节点数未超过 200
- **THEN** 系统 SHALL 渲染所有节点
- **AND** 不显示截断提示

#### Scenario: Search bypasses limit
- **WHEN** 用户使用搜索过滤节点
- **THEN** 系统 SHALL 渲染所有匹配节点及其邻居
- **AND** 不应用 Top-200 截断
