## ADDED Requirements

### Requirement: Sidebar reset on edge deletion
删除图谱关系（边）后，系统 SHALL 清空侧边栏中的选中实体详情，回退到实体列表视图。

#### Scenario: User deletes an edge from sidebar
- **WHEN** 用户在实体详情侧边栏中点击删除某条关系
- **AND** 删除操作成功
- **THEN** 系统 SHALL 清除 `nodeDetails` 状态
- **AND** 系统 SHALL 清除 `graphNodeDetail` 状态
- **AND** 侧边栏 SHALL 回退到显示全部实体列表
- **AND** 系统 SHALL 显示 toast 提示 "关系已删除"

#### Scenario: Edge deletion fails
- **WHEN** 用户在实体详情侧边栏中点击删除某条关系
- **AND** 删除操作失败
- **THEN** 系统 SHALL 保持当前侧边栏状态不变
- **AND** 系统 SHALL 显示错误 toast

### Requirement: D3 error visibility
D3 渲染错误 SHALL 对用户可见，而非静默吞噬。

#### Scenario: D3 rendering throws an error
- **WHEN** `drawGraph()` 执行过程中抛出异常
- **THEN** 系统 SHALL 捕获异常并设置 `graphError` 状态为错误消息
- **AND** SVG 区域 SHALL 显示 error overlay（含错误图标、"加载失败"标题、错误详情和"重试"按钮）

#### Scenario: User retries after error
- **WHEN** 用户点击 error overlay 中的"重试"按钮
- **THEN** 系统 SHALL 清除 `graphError` 状态
- **AND** 系统 SHALL 重新调用 `drawGraph()` 尝试渲染
