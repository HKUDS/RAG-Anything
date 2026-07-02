## Context

`KnowledgeGraphD3.jsx` 是一个使用 D3.js v7 力导向图渲染知识图谱的 React 组件。当前实现存在三个核心缺陷：

1. **力仿真永不停止**：`d3.forceSimulation` 未配置 `alphaDecay`/`alphaMin`，未调用 `sim.stop()`。D3 力仿真如不显式停止会无限运行，导致节点持续微动/弹跳
2. **缩放按钮为空实现**：ZoomIn/RotateCcw 按钮的 `onClick` 为 `() => {}`，UI 存在但完全无功能
3. **初始视图未适配**：加载后不执行 `zoom.fit()`，大型图谱可能部分节点超出可视区域

组件由 `ManufacturingKnowledgePage.jsx` 使用，该页面通过 tab 切换加载不同内容。组件内部直接调 API 获取数据，保持自包含。

技术栈：React + D3 v7 + Tailwind CSS + lucide-react 图标库。

## Goals / Non-Goals

**Goals:**
- 力仿真在布局稳定后自动停止，消除弹跳
- 缩放/重置按钮全部实际可用
- 加载后自动 fit-to-screen
- SVG 响应容器尺寸变化
- hover 高亮、拖拽视觉反馈、边标签

**Non-Goals:**
- 不改变数据模型或后端 API
- 不改变 ManufacturingKnowledgePage 中的使用方式
- 不引入新的外部依赖（D3 和 lucide-react 已存在）
- 不改变节点类型颜色/线型等视觉常量

## Decisions

### D1: 使用 `simulation.on('tick')` 内检查 alpha 并 stop
**选择**：在 tick 回调末尾检查 `sim.alpha() < 0.02` 时调用 `sim.stop()`
**替代方案**：配置 `alphaDecay` 和 `alphaMin` 让仿真自然终止。D3 v7 默认 alphaMin=0.001 且 alphaDecay≈0.0228（~300 次迭代），但需要在仿真终止时做 fit-to-screen 等后处理。实际上两者结合：配置 alphaDecay=0.0228，在 tick 中当 alpha<0.02 时主动 stop 并进行 fit。
**理由**：显式 stop 确保后处理时机可控，且防止极低 alpha 下的微抖动。

### D2: zoom 行为以 ref 存储，供按钮调用
**选择**：将 `d3.zoom()` 实例存储在 `useRef` 中，按钮 onClick 通过 ref 调用 `zoom.scaleBy()` 和 `zoom.transform()`
**替代方案**：使用 React state 驱动 zoom — 不适用，因为 D3 zoom 是独立的变换系统。
**理由**：D3 zoom 是命令式 API，ref 是最直接的桥接方式。

### D3: ResizeObserver 替代 window.resize
**选择**：使用 `ResizeObserver` 监听 SVG 父容器尺寸变化
**替代方案**：`window.addEventListener('resize', ...)` — 无法感知侧边栏展开等布局变化。
**理由**：容器级监听更准确，避免因其他 UI 变化导致的尺寸漂移。

### D4: 边标签使用 `<textPath>` 沿边显示
**选择**：为每条边创建 `<path>` (不可见) 作为 textPath 的引用轨道，再通过 `<text><textPath>` 显示标签
**替代方案**：直接用 `<text>` + transform 定位到边的中点 — 需要手动计算角度和位置。
**理由**：textPath 自动跟随边曲线，位置准确。对于直线边，创建一个沿直线的 path 即可。

### D5: hover 高亮通过 CSS transition + opacity 控制
**选择**：在 mouseenter/mouseleave 事件中修改节点/边的 `opacity` 属性，使用 D3 transition 平滑切换
**理由**：D3 内置的 transition 系统适合 SVG 属性动画，无需引入额外动画库。

## Risks / Trade-offs

- **[复杂度] 单文件组件可能变长** → 若超过 ~300 行，考虑拆分为 `useD3Graph` hook + 组件。当前预计 250 行以内可接受。
- **[性能] 200 节点 + 边标签可能导致渲染变慢** → 边标签使用简化路径（直线即可），避免复杂 SVG 结构。若节点数 > 200，截断到 200 并显示提示。
- **[兼容性] ResizeObserver 在极旧浏览器不支持** → 目标浏览器均为现代 Chrome/Firefox/Edge，ResizeObserver 支持度 97%+。
- **[回归] 拖拽行为变化可能影响用户习惯** → 拖拽后冷却机制使体验更好而非更差，风险低。
