## MODIFIED Requirements

### Requirement: D3 知识图谱力导向图 — 三层有序布局

系统 SHALL 在知识库页面的"知识图谱"标签页中根据节点数量自动选择三层有序布局策略：≤200 节点使用确定性同心圆布局，201-500 节点使用网格吸附力仿真布局，>500 节点使用确定性列式布局。

#### Scenario: 同心圆布局渲染（Tier 1）
- **WHEN** 图谱节点数 ≤200 且用户切换到"知识图谱"标签
- **THEN** 系统 SHALL 按 degree 降序将节点等分为 4 个同心圆环（分位数分配）
- **AND** 每圈内节点 SHALL 以自适应角间距分布（按节点半径 + 最小间距计算弧长需求）
- **AND** 节点 SHALL 始终保持在圆环位置上（环约束碰撞，仅调整角度不调整半径）
- **AND** 同一数据集每次渲染节点位置 SHALL 完全一致（确定性布局）

#### Scenario: 网格吸附力仿真布局（Tier 2）
- **WHEN** 图谱节点数在 201-500 之间
- **THEN** 系统 SHALL 先运行增强力仿真使节点自然分散形成拓扑团簇
- **AND** 力仿真收敛后 SHALL 将每个节点吸附到最近网格点
- **AND** 当两个节点竞争同一格点时，高 degree 节点优先占用，低 degree 节点 BFS 寻找最近空余格点
- **AND** 吸附后 SHALL 运行短暂微调仿真（≤20 tick，仅碰撞力）调整边长度
- **AND** 微调完成后 SHALL 锁定所有节点位置（设置 fx/fy）

#### Scenario: 列式布局（Tier 3）
- **WHEN** 图谱节点数 >500
- **THEN** 系统 SHALL 按 degree 降序将节点等分为 5-8 列
- **AND** 每列内节点 SHALL 均匀垂直排布，间距自适应画布高度
- **AND** 边 SHALL 使用贝塞尔曲线渲染，控制点偏移量与列间距成正比
- **AND** 同一数据集每次渲染节点位置 SHALL 完全一致（确定性布局）
- **AND** 默认不渲染标签，zoom > 1.2 时 SHALL 渲染当前可见区域内节点的标签

#### Scenario: 节点拖拽与回弹（Tier 1 同心圆模式）
- **WHEN** 用户在同心圆布局中拖拽某个节点到新位置后释放
- **THEN** 节点 SHALL 通过短暂力仿真平滑回弹到原同心圆位置
- **AND** 回弹过程 SHALL 在 500ms 内完成

#### Scenario: 节点拖拽与吸附（Tier 2 网格模式）
- **WHEN** 用户在网格吸附布局中拖拽某个节点到新位置后释放
- **THEN** 节点 SHALL 吸附到最近的空余网格点
- **AND** 若目标格点已被占用，SHALL BFS 寻找最近空余格点

#### Scenario: 节点拖拽（Tier 3 列式模式）
- **WHEN** 用户在列式布局中拖拽某个节点到新位置后释放
- **THEN** 节点 SHALL 保持在释放位置（不吸附、不回弹）

#### Scenario: 搜索过滤后 Tier 切换
- **WHEN** 用户通过搜索框过滤实体使显示节点数跨越 Tier 阈值
- **THEN** 系统 SHALL 使用新 Tier 的布局策略重新计算布局
- **AND** 布局切换 SHALL 同步完成，无中间态渲染

#### Scenario: "展示全部"触发 Tier 切换
- **WHEN** 用户点击"展示全部"按钮使显示节点数从 ≤200 变为 >500
- **THEN** 系统 SHALL 从 Tier 1 切换到 Tier 3（列式布局）
- **AND** 切换 SHALL 对用户透明（无报错、无卡顿）

#### Scenario: 标签策略（Tier 3 列式模式）
- **WHEN** 列式布局渲染中 zoom level ≤ 1.2
- **THEN** 系统 SHALL 不渲染节点标签
- **AND** hover 某个节点时 SHALL 渲染该节点及其直接邻居的标签
- **AND** 选中某个节点时 SHALL 始终渲染该节点标签

#### Scenario: 标签防重叠（Tier 1 同心圆模式）
- **WHEN** 同心圆布局渲染节点标签
- **THEN** 标签 SHALL 放置在节点远离圆心的外侧方向
- **AND** 标签位置 SHALL 避免与相邻节点重叠

### Requirement: 边渲染 — 有序布局

Tier 1 同圈节点之间的边 SHALL 渲染为弧线，跨圈边 SHALL 渲染为直线。Tier 2 所有边 SHALL 渲染为直线。Tier 3 同列边 SHALL 渲染为小偏移弧线，跨列边 SHALL 使用贝塞尔曲线渲染（控制点偏移量与列间距成正比）。所有 Tier 下边 SHALL 使用统一极淡色（`rgba(0,0,0,0.035)`），hover/select 时关联边加深为 `rgba(91,141,239,0.35)`。

### Requirement: 布局模式开关

系统 SHALL 提供 `USE_ORDERLY_LAYOUT` 编译时常量（默认 `true`），设置为 `false` 时所有 Tier 回退到纯力仿真布局。

## ADDED Requirements

### Requirement: 网格线渲染（Tier 2）
Tier 2 网格吸附布局下，系统 SHALL 可选渲染淡色网格线（`rgba(0,0,0,0.03)`）作为背景装饰，网格线间距等于 `cellSize`。

### Requirement: 列式布局 hover 高亮（Tier 3）
Tier 3 列式布局下 hover 节点时，系统 SHALL 渲染：该节点放大（半径 +3px）、该节点的标签浮现、该节点的直接关联边高亮（`rgba(91,141,239,0.4)`）。

## REMOVED Requirements

无。现有 Canvas 渲染、缩放交互、hit-test、错误处理等要求保持不变。
