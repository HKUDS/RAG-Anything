## Phase 1: Canvas 基础设施

- [ ] **1.1** 在 `KnowledgeDetailPage.jsx` 的 graph tab JSX 中，将 `<svg ref={svgRef}>` 替换为 `<canvas ref={canvasRef}>`
- [ ] **1.2** 实现 `render()` 核心绘制函数：clearRect → 边 → 节点 → 标签（参考 design.md Decision 5 绘制顺序）
- [ ] **1.3** 实现 DPR 缩放：`canvas.width = W * dpr`，`canvas.style.width = W + 'px'`
- [ ] **1.4** 新增 `canvasRef`（useRef）替代 `svgRef`，保留 `svgRef` 用于向后兼容

## Phase 2: 力仿真 + 缩放迁移

- [ ] **2.1** 保留 `d3.forceSimulation()` 全部配置，将 `sim.on('tick')` 中的 DOM 操作替换为 `requestRender()`
- [ ] **2.2** 保留 `d3.zoom()` 变换计算，`on('zoom')` 中存储 `{x, y, k}` 并调用 `requestRender()`
- [ ] **2.3** zoom 事件绑定从 `svgEl.call(zoom)` 改为 `canvas.addEventListener('wheel', ...)` + pointer 事件

## Phase 3: 交互迁移

- [ ] **3.1** 实现 `screenToSim(clientX, clientY)` 坐标转换函数
- [ ] **3.2** 实现 `hitTestNodes(simX, simY)` 圆形命中检测
- [ ] **3.3** 节点拖拽：`pointerdown` → hitTest → 锁定节点 → `pointermove` 更新 fx/fy → `pointerup` 释放
- [ ] **3.4** 节点点击：`click` → hitTest → 选中节点 → 获取详情（复用现有 fetchNodeDetail 逻辑）
- [ ] **3.5** 悬停高亮：`pointermove` → hitTest → 更新 `hoveredNode` 状态 → requestRender
- [ ] **3.6** 画布空白区点击：`click`（无 hit）→ clear selection

## Phase 4: 渲染优化

- [ ] **4.1** requestAnimationFrame 合并去重（`renderPending` 标志位）
- [ ] **4.2** 标签渲染条件：仅 `displayNodes.length ≤ 200` 或 `zoom.k > 1.5` 时渲染文字
- [ ] **4.3** 线宽反比缩放：边宽、描边宽 × `1/k`，避免缩小时线过粗
- [ ] **4.4** ResizeObserver 更新 canvas 尺寸（替换现有 container resize 监听）

## Phase 5: 回退与验证

- [ ] **5.1** 添加 `USE_CANVAS = true` 开关常量，`false` 时走原有 SVG 代码路径
- [ ] **5.2** 保留原有 `drawGraph()` SVG 代码（`if (!USE_CANVAS)` 分支），待稳定后删除
- [ ] **5.3** 小图（≤50 节点）行为对比测试：Canvas vs SVG 视觉效果一致
- [ ] **5.4** 大图（1000 节点）性能验证：帧率 ≥30 FPS，拖拽 <50ms
- [ ] **5.5** ResizeObserver 响应式验证
- [ ] **5.6** 错误处理：渲染异常时显示错误遮罩
- [ ] **5.7** "展示全部"按钮功能验证（与 Canvas 渲染兼容）
