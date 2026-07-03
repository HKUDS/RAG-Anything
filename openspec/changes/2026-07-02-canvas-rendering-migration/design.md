# Canvas Rendering Design

## Context

`KnowledgeDetailPage.drawGraph()` 当前完全基于 SVG DOM 渲染 D3 力导向图。每次 simulation tick 执行数千次 DOM 属性更新（`circle.attr('cx')`, `text.attr('x')`, `line.attr('x1')` 等），导致浏览器重排/重绘风暴。1000 节点场景下帧率降至 2-5 FPS。

**Canvas 方案**：将渲染目标从 `<svg>` 换成 `<canvas>`，每个 tick 在一次 2D 绘制调用中完成所有节点/边的渲染。力仿真逻辑完全不动。

## Goals / Non-Goals

**Goals:**
- 1000 节点场景 30+ FPS，可流畅拖拽缩放
- 保留全部现有交互：拖拽节点、缩放/平移、悬停高亮、点击选中实体
- 保留现有视觉：节点颜色/大小映射、边线、文字标签
- 零 API 变更，纯前端渲染层替换
- 小图（≤200 节点）行为不变

**Non-Goals:**
- 不改 KnowledgeGraphD3（制造知识图谱页）
- 不引入 WebGL/d3-force-3d（过度工程）
- 不重构状态管理或数据流
- 不支持节点图片/图标（当前 SVG 也没有）

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  React State                      │
│  graph / graphSearch / showAllNodes / selectedNode│
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│            drawGraph() 主函数                     │
│                                                   │
│  1. 数据过滤 (filteredNodes → displayNodes)       │
│  2. D3 力仿真 (forceSimulation — 不变)            │
│  3. Canvas 渲染 (新) ← 替换 SVG DOM 操作           │
│  4. 交互绑定 (新 Canvas 事件模型)                  │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│            <canvas> DOM 元素                      │
│  - 单层绘制：边 → 节点 → 标签 → 高亮遮罩          │
│  - requestAnimationFrame 驱动重绘                 │
│  - ctx.getImageData() 实现 hit-test               │
└─────────────────────────────────────────────────┘
```

## Decisions

### Decision 1: Canvas 2D over WebGL/PixiJS

**选择**：原生 Canvas 2D API，不引入第三方渲染库。

**替代方案**：
- **PixiJS**：WebGL 渲染快 2-3 倍，但引入 500KB 依赖，需学习新 API
- **d3-canvas**：社区方案不成熟
- **deck.gl**：为地图可视化设计，通用图布局反而不方便

**理由**：
- Canvas 2D 渲染 1000 节点绰绰有余（WebGL 的优势在 10000+ 节点才明显）
- 零额外依赖，bundle 不增加
- drawCircle/drawLine/drawText 三个原语即可覆盖
- hit-test 用 `ctx.isPointInPath()` 简单可靠

**Trade-off**：放弃 D3 的声明式 transition（`.transition().duration(400)`），需自己用 `requestAnimationFrame` 实现。但 D3 的 transition 在大图时本身就是性能杀手。

### Decision 2: 保留 D3 力仿真 + 缩放/平移

**选择**：D3 的 `forceSimulation`、`forceLink`、`forceManyBody`、`forceCenter`、`forceCollide` 全部保留。D3 的 `d3.zoom()` 也保留，但只用于计算变换矩阵，不驱动 DOM 更新。

```js
// 力仿真：完全不动
const sim = d3.forceSimulation(displayNodes)
  .force('link', d3.forceLink(displayEdges).id(d => d.id).distance(...))
  .force('charge', d3.forceManyBody().strength(...))
  .force('center', d3.forceCenter(W / 2, H / 2))
  .force('collision', d3.forceCollide().radius(...))
  .alphaDecay(...).alphaMin(...).velocityDecay(...)
  .on('tick', () => requestAnimationFrame(render))  // tick → 请求重绘
  .on('end', () => { /* 最终一次绘制 */ })

// 缩放：用 transform 矩阵做坐标变换
const zoom = d3.zoom()
  .scaleExtent([0.3, 4])
  .on('zoom', (e) => {
    transform = e.transform  // 存起来，render() 里用
    requestAnimationFrame(render)
  })
// zoom 不再绑在 svg 上，而是监听 canvas 的 wheel/pointer 事件
```

**理由**：D3 force 算法成熟、参数可调，没有等价的轻量替代。Canvas 只替换渲染输出。

### Decision 3: Canvas 事件模型

**选择**：在 `<canvas>` 上监听原生事件，自己实现 hit-test。

```js
// 鼠标位置从屏幕坐标转换到力仿真坐标
function screenToSim(clientX, clientY) {
  const rect = canvas.getBoundingClientRect()
  return {
    x: (clientX - rect.left - transform.x) / transform.k,
    y: (clientY - rect.top - transform.y) / transform.k,
  }
}

// Hit-test: 点在哪个节点上？
function hitTestNodes(simX, simY) {
  // 从后往前遍历（后绘制的在上面）
  for (let i = displayNodes.length - 1; i >= 0; i--) {
    const n = displayNodes[i]
    const r = sizeScale(n.degree) + 4  // +4 padding
    const dx = simX - n.x
    const dy = simY - n.y
    if (dx * dx + dy * dy <= r * r) return n
  }
  return null
}
```

**事件映射**：

| SVG 事件 | Canvas 事件 |
|----------|------------|
| `nodeGroup.on('click')` | `canvas.onclick` + hitTest |
| `nodeGroup.call(d3.drag())` | `canvas.onpointerdown/move/up` + hitTest + 更新 fx/fy |
| `svgEl.call(zoom)` | `canvas.onwheel` + `canvas.onpointerdown/move/up`（平移） |
| `nodeGroup.on('mouseenter/leave')` | `canvas.onpointermove` + hitTest 状态跟踪 |

### Decision 4: 渲染循环

**选择**：事件驱动 + requestAnimationFrame 合并，不使用持续渲染循环。

```js
let renderPending = false

function requestRender() {
  if (renderPending) return
  renderPending = true
  requestAnimationFrame(() => {
    render()
    renderPending = false
  })
}

// 触发源：
// 1. sim.on('tick') → requestRender()
// 2. zoom.on('zoom') → requestRender()
// 3. 拖拽中 pointermove → requestRender()
// 4. 悬停状态改变 → requestRender()
```

**理由**：不需要持续 60fps。力仿真 tick 在稳定期不再触发，悬停/拖拽是离散事件。合并多次请求避免一帧内重复绘制。

### Decision 5: 绘制顺序与分层

**选择**：单层 Canvas，固定绘制顺序：

```
1. clearRect() — 清空
2. 边（线）— 透明度随选中/悬停状态变化
3. 节点（圆）— 颜色按类型，大小按 degree
4. 节点标签（文字）— 仅对 degree≥2 或 ≤50 节点的图
5. 悬停高亮环（如果存在）— 金色描边加粗
6. 选中高亮环（如果存在）— 天蓝色描边加粗
```

不需要多层 Canvas。1000 节点全量重绘在 Canvas 2D 上只需 ~5ms。

### Decision 6: 低 DPI 设备优化

**选择**：Canvas 分辨率按 `devicePixelRatio` 缩放以避免模糊。

```js
const dpr = window.devicePixelRatio || 1
canvas.width = W * dpr
canvas.height = H * dpr
canvas.style.width = W + 'px'
canvas.style.height = H + 'px'
ctx.scale(dpr, dpr)
```

## Implementation Sketch

```js
// ─── 渲染函数 ───
function render() {
  const ctx = canvas.getContext('2d')
  const { x, y, k } = transform  // d3.zoom transform

  ctx.save()
  ctx.clearRect(0, 0, W, H)

  // 应用缩放+平移
  ctx.translate(x, y)
  ctx.scale(k, k)

  // 1. 画边
  displayEdges.forEach(e => {
    if (!e.source.x) return
    ctx.beginPath()
    ctx.moveTo(e.source.x, e.source.y)
    ctx.lineTo(e.target.x, e.target.y)
    ctx.strokeStyle = edgeColor(e, hoveredNode, selectedNode)
    ctx.lineWidth = edgeWidth(e, hoveredNode) / k  // 线宽反比缩放
    ctx.stroke()
  })

  // 2. 画节点
  displayNodes.forEach(n => {
    if (n.x === undefined) return
    const r = sizeScale(n.degree)
    ctx.beginPath()
    ctx.arc(n.x, n.y, r, 0, 2 * Math.PI)
    ctx.fillStyle = colorScale(n.id)
    ctx.strokeStyle = isSelected(n) ? '#3b82f6' : (isHovered(n) ? '#f59e0b' : '#d6e5f2')
    ctx.lineWidth = (isSelected(n) || isHovered(n) ? 3 : 1) / k
    ctx.fill()
    ctx.stroke()
  })

  // 3. 画标签（仅小/中图，或缩放足够大时）
  if (displayNodes.length <= 200 || k > 1.5) {
    ctx.fillStyle = '#2d4d66'
    ctx.textAlign = 'center'
    displayNodes.forEach(n => {
      const fontSize = Math.max(7, Math.min(11, sizeScale(n.degree) * 0.7)) / k
      ctx.font = `${fontSize}px "Microsoft YaHei", sans-serif`
      ctx.fillText((n.label || n.id || '').slice(0, 10), n.x, n.y + sizeScale(n.degree) + 12 / k)
    })
  }

  ctx.restore()
}
```

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| **Canvas 文字渲染质量低于 SVG** | Canvas `ctx.fillText()` 在 HiDPI 下质量足够；缩放 >1.5x 时渲染标签 |
| **hit-test 精度** | 圆形范围检测 ± 4px padding，点击体验与 SVG 一致 |
| **失去 CSS hover 效果** | 手动跟踪 `hoveredNode` 状态，重绘时画高亮环 |
| **浏览器兼容性** | Canvas 2D 支持率 97%+（IE 除外），项目已无需兼容 IE |
| **代码可读性** | Canvas 绘制逻辑集中在一个 render() 函数，反而比分散的 .attr() 调用更清晰 |
| **测试难度** | Canvas 像素级测试困难，但交互行为可通过状态测试覆盖 |

## Rollback Plan

1. `drawGraph()` 中新增 `USE_CANVAS = true` 开关常量
2. 设为 `false` 即回退到原有 SVG 路径（保留旧代码路径一个版本）
3. 验证稳定后删除 SVG 分支和开关
