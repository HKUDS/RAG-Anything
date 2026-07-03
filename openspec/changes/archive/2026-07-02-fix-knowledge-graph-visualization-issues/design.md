## Context

当前项目有两个知识图谱 D3 可视化实现：

1. **KnowledgeGraphD3.jsx** — 可复用组件，用于制造知识图谱页面（`ManufacturingKnowledgePage`）。功能完善（图例、tooltip、类型筛选、响应式），但边标签是死代码、搜索不展开邻居。

2. **KnowledgeDetailPage.jsx 内联 D3** — 知识库详情页中的图谱标签页，包含实体 CRUD 和侧边栏。功能更多但 UX 粗糙：空搜索无提示、节点上限不一致、边删除后侧边栏陈旧、SVG 高度浪费、错误静默吞噬。

两个组件各有优劣，本次修复聚焦 KnowledgeDetailPage（用户主要使用的图谱入口），对 KnowledgeGraphD3 做最小化清理。

## Goals / Non-Goals

**Goals:**
- 修复 KnowledgeDetailPage 图谱的 6 个严重 UX 缺陷
- 清理 KnowledgeGraphD3 中的死代码
- 统一两个组件的搜索行为（邻居展开）
- 让 D3 错误对用户可见并提供恢复路径

**Non-Goals:**
- 不合并两个 D3 实现（架构重构，风险太高，另案处理）
- 不改变现有 API 接口
- 不修改后端代码
- 不增加新的 npm 依赖

## Decisions

### Decision 1: 搜索空状态采用带提示的空白 SVG overlay

**选择**：在 SVG 容器内叠加一个绝对定位的半透明提示层，文字"无匹配实体"，下方提供"清除搜索"按钮。

**理由**：
- 不改变 SVG/D3 的 DOM 结构，避免与 simulation/tick 逻辑冲突
- 视觉上与 loading/error 状态保持一致的设计语言
- "清除搜索"按钮让用户能快速恢复

**备选方案**：在 SVG 内用 D3 渲染文字 — 缺点是需要额外处理 zoom transform，且搜索词变化时文字不会随 zoom 移动。

### Decision 2: 统一节点上限为 100，搜索时也截断并提示

**选择**：
- 无搜索：显示前 100 个节点（从 60 提升到 100）
- 有搜索：显示前 100 个匹配节点 + 其直接邻居（邻居也计入 100 限制内）
- 当实际节点数超过显示数时，显示 "显示 100/150 个节点" 提示

**理由**：
- 100 是 D3 力导向图在不明显卡顿前提下的合理上限
- 统一上限避免搜索/非搜索体验割裂
- 提示文本让用户知晓数据被截断

**备选方案**：完全去掉上限 — 缺点：大知识库（500+ 节点）时 D3 仿真会严重卡顿甚至浏览器无响应。

### Decision 3: 边删除后清空侧边栏状态

**选择**：在 `handleDeleteEdge` 成功后，将 `nodeDetails` 和 `graphNodeDetail` 均设为 `null`，侧边栏回退到实体列表视图。

**理由**：
- 最简单的修复 — 一行代码
- 比"局部更新 connectionList"更安全（避免边计数、关联实体列表等派生状态不一致）
- 用户删除边后本来就需要重新审视实体关系，回到列表视图是合理行为

**备选方案**：从 `nodeDetails.connections` 中 `filter` 出被删除的边 — 缺点：还需要更新 `totalConnections`、`connectedNodes`、`graphNodeDetail.relation_count` 等多个关联状态，容易遗漏。

### Decision 4: SVG 高度从容器计算

**选择**：用 `graphContainerRef.current?.clientHeight` 替代硬编码的 420，并设置 `minHeight: 350`。

**理由**：
- 容器已设置 `flex-1`，实际高度约 450px（520px - 工具栏 60px），当前只用 420 浪费约 30-80px
- 动态计算适配不同窗口大小，与 KnowledgeGraphD3 的 ResizeObserver 方案精神一致
- 保留 minHeight 确保极小窗口下仍可用

### Decision 5: 错误状态提升到组件级别

**选择**：新增 `graphError` state，`drawGraph` 的 catch 块中 `setGraphError(error.message)`，在 SVG 区域渲染 error overlay（复用现有 error UI 模式）。

**理由**：
- 与 `loading`/`error` props 的设计模式一致（已存在于 KnowledgeGraphD3）
- 用户至少知道"出了问题"并能重试
- 不改变 drawGraph 的函数签名

### Decision 6: KnowledgeGraphD3 边标签死代码 — 直接删除

**选择**：删除整个 `drawEdgeLabels()` 函数及其调用（约 30 行），以及 `edgeLabelsDrawn` 标志和 `renderId` 相关的 path 定义。

**理由**：
- 注释已明确声明 "edge text labels disabled — legend already indicates line meaning"
- textPath 元素中 `.text('')` 永远不会显示任何内容
- 每次渲染都创建 30+ 个空 DOM 元素是纯性能浪费
- `renderId` 参数将不再被需要（它仅为 edge path ID 去重而存在）

**备选方案**：实现真正的边标签 — 缺点：增加视觉复杂度，且 KnowledgeDetailPage 已经实现了简化版边标签（10 字符截断）。

### Decision 7: KnowledgeGraphD3 搜索邻居展开

**选择**：在 `filteredNodes` 的 useMemo 中，当 searchTerm 非空时，额外包含匹配节点的所有直接邻居（双向）。

**理由**：
- 与 KnowledgeDetailPage 的搜索行为一致（line 441-449）
- 邻接图（adjacency map）已在 D3 effect 中构建，可以上提到 useMemo 层共享
- 避免搜索到孤立节点时用户看不到关系上下文

## Risks / Trade-offs

- **[性能] 节点上限 100 对大知识库仍有卡顿风险**：100 个节点 + 数百条边时 D3 仿真仍需 ~2-5 秒稳定。→ 可接受，比之前无限节点好得多。后续可考虑虚拟化或 WebGL 渲染。
- **[用户体验] 边删除后跳回列表视图**：用户可能预期停留在当前实体详情中看到"已删除"的反馈。→ 权衡：显示 toast "关系已删除"提供反馈，回退到列表是合理的默认行为。
- **[兼容性] ResizeObserver 在旧浏览器不可用**：KnowledgeGraphD3 已做 guard（`typeof ResizeObserver === 'undefined'` 时跳过）。KnowledgeDetailPage 不依赖 ResizeObserver，用 `clientHeight` 在 drawGraph 时读取一次即可。

## Open Questions

- 是否需要在 KnowledgeDetailPage 中也增加 ResizeObserver 以响应窗口缩放？（当前只在 drawGraph 触发时读取一次高度，切换标签时不会重绘）
- 将来是否合并两个 D3 实现为一个统一的 `KnowledgeGraphD3` 组件，通过 props 控制 CRUD 功能开关？
