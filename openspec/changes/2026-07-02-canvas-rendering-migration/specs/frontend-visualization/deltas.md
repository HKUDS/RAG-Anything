## MODIFIED Requirements

### Requirement: D3 知识图谱力导向图
系统 SHALL 在知识库页面的"知识图谱"标签页中集成 D3 力导向图，展示赛项知识节点及其关系。渲染 SHALL 使用 Canvas 2D 替代 SVG DOM，以确保 1000+ 节点场景下的流畅交互。

#### Scenario: 图谱渲染
- **WHEN** 用户切换到"知识图谱"标签
- **THEN** 系统 SHALL 在 Canvas 元素上渲染包含所有知识节点的力导向图，节点按类型着色（知识点/赛题/技能），边按关系类型显示不同线型
- **AND** 图谱显示节点数 SHALL 不超过 200 个（按 degree 降序），超出时在图形下方显示截断提示和"展示全部"按钮
- **AND** 渲染帧率在 1000 节点场景 SHALL 不低于 30 FPS

#### Scenario: 节点交互
- **WHEN** 用户点击图谱中的某个节点
- **THEN** 系统 SHALL 通过 Canvas hit-test 定位点击节点，高亮该节点及其邻接节点，并在侧边栏展示节点详情和谱系信息

#### Scenario: 缩放与拖拽
- **WHEN** 用户滚轮缩放或拖拽画布
- **THEN** 图谱 SHALL 通过 Canvas transform 平滑缩放/平移，节点位置随之更新
- **AND** 拖拽延迟 SHALL 不超过 50ms

#### Scenario: 悬停高亮
- **WHEN** 用户鼠标悬停在某个节点上
- **THEN** 系统 SHALL 通过 pointermove + hit-test 定位悬停节点
- **AND** 悬停节点 SHALL 渲染为高亮状态（金色描边加粗，透明度变化）

#### Scenario: 图谱容器高度自适应
- **WHEN** 图谱容器渲染
- **THEN** Canvas 高度 SHALL 根据父容器 `clientHeight` 动态计算
- **AND** Canvas 高度 SHALL 不低于 350px
- **AND** Canvas 分辨率 SHALL 按 `devicePixelRatio` 缩放以避免模糊

#### Scenario: 渲染错误可见
- **WHEN** Canvas 渲染过程中发生异常
- **THEN** 系统 SHALL 显示错误遮罩层（含错误描述和重试按钮）
- **AND** 错误信息 SHALL 对用户可见

## REMOVED Requirements

### Requirement: 边标签渲染（KnowledgeDetailPage）
KnowledgeDetailPage 的 D3 图 SHALL NOT 渲染边标签。Canvas 迁移后此要求自然满足。
