## Why

知识图谱 D3 可视化组件（`KnowledgeGraphD3.jsx`）存在严重的用户体验缺陷：力导向图仿真从不停止导致节点无限弹跳、缩放/重置按钮完全失效、初始视图未自适应居中。用户反馈"画面不经控制跳动，整个效果差强人意"，这些问题直接影响知识库功能的可用性和专业感。

## What Changes

- **修复力仿真永不停止**：设置 `alphaDecay`/`alphaMin` 并在 alpha 降至阈值时调用 `sim.stop()`，消除节点无限弹跳
- **实现缩放/重置按钮**：连接 D3 zoom 行为的 `scaleBy`/`transform` 方法，实现放大、缩小、重置三个控件的实际功能
- **初始视图自适应**：加载完成后自动调用 `zoom.fit()` 使所有节点居中可见
- **自适应容器尺寸**：SVG 高度改为响应式（根据父容器动态计算），监听 `ResizeObserver` 更新力场中心
- **增强拖拽体验**：拖拽时显示视觉反馈（节点放大/阴影），释放后添加冷却期防止剧烈回弹
- **边关系标签**：在边上显示关系类型标签（前驱/进阶/相关）
- **节点 hover 状态**：hover 时高亮节点及其邻接边，降低其他元素透明度
- **窗口缩放适配**：监听 resize 事件更新 SVG 尺寸和力场中心

## Capabilities

### New Capabilities
- `knowledge-graph-stabilization`: 力仿真稳定化 — 自动停机和冷却控制，消除无限弹跳
- `knowledge-graph-controls`: 图谱缩放控件 — 放大/缩小/重置/自适应按钮的功能实现
- `knowledge-graph-interaction`: 图谱交互增强 — hover 高亮、拖拽反馈、自适应容器

### Modified Capabilities
- `frontend-visualization`: D3 知识图谱力导向图的渲染、交互、缩放需求细化 — 补充稳定化约束、响应式尺寸要求、控件功能规范

## Impact

- 修改文件：`frontend/src/components/KnowledgeGraphD3.jsx`（核心重构）
- 无 API 变更，无后端影响
- 依赖：d3 (已有), lucide-react (已有)
