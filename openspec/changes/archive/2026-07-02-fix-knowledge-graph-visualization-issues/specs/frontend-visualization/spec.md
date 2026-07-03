## MODIFIED Requirements

### Requirement: D3 知识图谱力导向图
系统 SHALL 在知识库页面的"知识图谱"标签页中集成 D3 力导向图，展示赛项知识节点及其关系。

#### Scenario: 图谱渲染
- **WHEN** 用户切换到"知识图谱"标签
- **THEN** 系统 SHALL 渲染包含所有知识节点的力导向图，节点按类型着色（知识点/赛题/技能），边按关系类型显示不同线型
- **AND** 图谱显示节点数 SHALL 不超过 100 个，超出时在图形下方显示截断提示

#### Scenario: 节点交互
- **WHEN** 用户点击图谱中的某个节点
- **THEN** 系统 SHALL 高亮该节点及其邻接节点，并在侧边栏展示节点详情和谱系信息

#### Scenario: 缩放与拖拽
- **WHEN** 用户滚轮缩放或拖拽画布
- **THEN** 图谱 SHALL 平滑缩放/平移，节点位置随之更新

#### Scenario: 图谱容器高度自适应
- **WHEN** 图谱容器渲染
- **THEN** SVG 高度 SHALL 根据父容器 `clientHeight` 动态计算
- **AND** SVG 高度 SHALL 不低于 350px

#### Scenario: 渲染错误可见
- **WHEN** D3 渲染过程中发生异常
- **THEN** 系统 SHALL 显示错误遮罩层（含错误描述和重试按钮）
- **AND** 错误信息 SHALL 对用户可见

## REMOVED Requirements

### Requirement: 看板实时更新
**Reason**: KnowledgeDetailPage 不再使用独立的看板轮询组件，图谱数据通过 8 秒轮询自动更新。
**Migration**: 无迁移需求，功能已由 KnowledgeDetailPage 内建轮询替代。
