# Orderly Graph Layout — Design

## Context

`KnowledgeDetailPage.drawGraph()` 当前对 ≤200 节点使用同心圆布局，>200 节点使用增强力仿真。用户反馈 **200+ 节点场景仍然混乱**——力仿真的物理本质决定了它永远无法产生"规整"的视觉效果。

根本问题：力仿真 = 模拟弹簧系统 = 天然倾向混乱。大图需要**确定性布局**，而非更强的物理约束。

## Goals / Non-Goals

**Goals:**
- ≤200 节点：保持同心圆布局，修复碰撞仿真破坏圆环的问题
- 200-500 节点：网格吸附力仿真——保留图结构的空间语义 + 网格对齐的规整感
- 500+ 节点：列式布局——绝对确定性、零随机、最大节点密度
- 同一数据每次渲染节点位置完全一致（确定性）
- 保留缩放/平移/拖拽/点击/悬停全部交互

**Non-Goals:**
- 不引入第三方布局库
- 不改 Canvas 渲染代码结构（只改布局计算）
- 不改 KnowledgeGraphD3 组件（制造知识图谱页）
- 不支持用户手动切换布局模式

## Three-Tier Layout Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                     节点数 → 布局选择                              │
│                                                                   │
│    0 ─────────── 200 ─────────── 500 ─────────── ∞               │
│         Tier 1           Tier 2           Tier 3                  │
│    同心圆布局          网格吸附力仿真       列式布局                 │
│    (已有,需修碰撞)     (新)               (新)                     │
│                                                                   │
│    特点:               特点:              特点:                    │
│    • 中心-外围语义     • 保留拓扑关系       • 绝对确定性             │
│    • 固定圆环位置      • 网格对齐规整       • 按 degree 分列         │
│    • 节点不离开圆环    • 收敛后吸附格点     • 列内均匀垂直排布       │
│                       • 冲突时低度让位     • 可容纳 1000+ 节点      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tier 1: 同心圆布局（≤200 节点）

### Decision 1.1: 修复碰撞仿真 — 环约束替代自由碰撞

**问题**：当前实现先用同心圆排好节点，再跑 50 tick 的纯 `forceCollide` 仿真。碰撞仿真没有 `forceRadial` 约束，节点被推离圆环位置，破坏了同心圆结构。

**修复方案**：删除 50 tick 自由碰撞仿真，改为**环上角度碰撞解决**——只调整节点在圆环上的角度，不改变半径。

```js
function resolveRingCollisions(ringNodes, radius, cx, cy, sizeScale) {
  // Sort by angle
  ringNodes.sort((a, b) => {
    const aa = Math.atan2(a.y - cy, a.x - cx)
    const ba = Math.atan2(b.y - cy, b.x - cx)
    return aa - ba
  })

  // Check adjacent pairs — if too close, spread apart on the ring
  const n = ringNodes.length
  const totalArc = 2 * Math.PI
  let totalDemand = 0
  const demands = ringNodes.map(node => {
    const nodeR = sizeScale(node.degree)
    return (2 * nodeR + 10) / radius  // angular demand in radians (diameter + gap)
  })

  totalDemand = demands.reduce((s, d) => s + d, 0)

  // If total demand exceeds circumference, we have overflow
  // → keep angles proportional to demand, accept some overlap
  // → mark overflow nodes for label hiding

  // Otherwise, distribute with exact spacing
  let angle = -Math.PI / 2  // start from 12 o'clock
  ringNodes.forEach((node, i) => {
    const halfArc = demands[i] / 2
    angle += halfArc
    node.x = cx + radius * Math.cos(angle)
    node.y = cy + radius * Math.sin(angle)
    angle += halfArc
  })

  return { overflow: totalDemand > totalArc }
}
```

### Decision 1.2: 分位数环形分配

**问题**：当前用 `ratio > 0.5 / 0.2 / 0.03` 分配节点到 4 层。幂律度分布下，绝大部分节点（ratio ≤ 0.03）挤在外圈。

**修复**：按节点数等分为 4 组（分位数），而非按 degree 绝对值比例。

```js
// 现在（有问题）:
// ratio > 0.5 → 2 个节点，ratio ≤ 0.03 → 120 个节点

// 改为（分位数）:
const sorted = [...nodes].sort((a, b) => (b.degree || 0) - (a.degree || 0))
const perRing = Math.ceil(sorted.length / 4)
const rings = [
  sorted.slice(0, perRing),                    // top 25%
  sorted.slice(perRing, perRing * 2),          // 50-75%
  sorted.slice(perRing * 2, perRing * 3),      // 25-50%
  sorted.slice(perRing * 3),                   // bottom 25%
]
```

---

## Tier 2: 网格吸附力仿真（201-500 节点）

### Decision 2.1: 力仿真 + 网格吸附

**选择**：先跑增强力仿真让节点自然分布（保留拓扑关系），收敛后将每个节点吸附到最近的网格点。冲突时低 degree 节点让位。

**理由**：
- 力仿真确保"连接的节点彼此靠近"——图结构有空间意义
- 网格吸附确保"节点在整齐的网格线上"——视觉规整
- 两者叠加：既反映拓扑关系，又看起来整齐

**算法流程**：

```
1. 跑力仿真（使用已增强的参数: strength(-250), collision(+18), alphaDecay(0.08)）
   → 节点自然分散，形成拓扑团簇

2. 等待仿真收敛 (alpha < alphaMin 或 tick 超时)
   → 节点位置稳定

3. 构建网格:
   cellSize = max(节点最大直径 + 8px, 24px)
   cols = floor(W / cellSize)
   rows = floor(H / cellSize)
   grid = new Set()  // 记录已占用的格点

4. 按 degree 降序遍历节点:
   - 计算最近格点 (gx, gy)
   - 如果 (gx, gy) 未被占用 → 占用，节点吸附到 (gx, gy)
   - 如果已被占用 → BFS 找最近空余格点 → 节点吸附到那里

5. 短暂力仿真微调 (10-20 tick, 无 link force, 仅碰撞):
   → 让边长度自然调整，避免吸附后出现极端长边

6. 最终渲染: 所有节点在网格点上
```

**BFS 冲突解决**：

```js
function findNearestEmptyCell(gx, gy, grid, cols, rows, cellSize) {
  const visited = new Set()
  const queue = [[gx, gy, 0]]
  visited.add(`${gx},${gy}`)

  while (queue.length > 0) {
    const [cx, cy, dist] = queue.shift()
    if (!grid.has(`${cx},${cy}`) &&
        cx >= 0 && cx < cols * cellSize &&
        cy >= 0 && cy < rows * cellSize) {
      return { x: cx, y: cy }
    }
    // Expand to neighbors (Manhattan distance)
    for (const [dx, dy] of [[0,cellSize],[cellSize,0],[0,-cellSize],[-cellSize,0]]) {
      const nx = cx + dx, ny = cy + dy
      const key = `${nx},${ny}`
      if (!visited.has(key)) {
        visited.add(key)
        queue.push([nx, ny, dist + 1])
      }
    }
  }
  return { x: gx + cellSize, y: gy }  // fallback
}
```

### Decision 2.2: 网格吸附的视觉参数

| 参数 | 值 | 说明 |
|------|---|------|
| cellSize | `max(24, maxNodeDiameter + 8)` | 格点间距 |
| 标签显示 | zoom > 0.5 或 hover | 200+ 节点全显标签会重叠 |

---

## Tier 3: 列式布局（500+ 节点）

### Decision 3.1: 按 degree 分列，列内垂直均匀排布

**选择**：500+ 节点放弃力仿真，改用纯确定性列式布局。

**理由**：
- 500 节点时，即使用网格吸附，格点间距也会缩减到 ~20px——标签不可读，视觉仍显拥挤
- 列式布局将 2D 空间问题降为 1D（每列只需垂直排列），空间利用效率最高
- 完全确定性——同一数据永远同一位置

**算法**：

```js
function columnLayout(nodes, W, H) {
  const sorted = [...nodes].sort((a, b) => (b.degree || 0) - (a.degree || 0))
  const margin = 40  // px from edge

  // Determine column count based on node count
  const numCols = nodes.length <= 600 ? 5 :
                  nodes.length <= 800 ? 6 :
                  nodes.length <= 1000 ? 7 : 8

  // Split into equal-sized columns by degree rank
  const perCol = Math.ceil(sorted.length / numCols)
  const columns = []
  for (let i = 0; i < numCols; i++) {
    columns.push(sorted.slice(i * perCol, (i + 1) * perCol))
  }
  // columns[0] = highest degree hubs, columns[N-1] = leaf nodes

  const colWidth = (W - 2 * margin) / (numCols - 1)
  const availH = H - 2 * margin

  columns.forEach((colNodes, ci) => {
    const colX = margin + ci * colWidth
    const spacing = colNodes.length > 1
      ? availH / (colNodes.length - 1)
      : availH / 2  // single node: center vertically

    colNodes.forEach((n, i) => {
      n.x = colX
      n.y = margin + i * spacing
      n._colIndex = ci
    })
  })

  return { columns }
}
```

### Decision 3.2: 列式模式下的边渲染

**选择**：边用贝塞尔曲线连接，控制点偏移量与列间距成正比。500+ 节点场景下默认不渲染标签。

```
同列边:     │              相邻列边:  ╭─╮           跨多列边:  ╭─────╮
            │                        ╱ ╲                      ╱       ╲
            ●                        ●   ●                    ●         ●
            │                        ╲ ╱                      ╲       ╱
            ●                        ╰─╯                      ╰─────╯
```

```js
function drawColumnEdge(ctx, source, target, W, H) {
  const sx = source.x, sy = source.y
  const tx = target.x, ty = target.y
  const colDist = Math.abs((source._colIndex || 0) - (target._colIndex || 0))

  if (colDist === 0) {
    // Same column: tiny horizontal offset arc
    const offset = 8
    ctx.quadraticCurveTo(sx + offset, (sy + ty) / 2, tx, ty)
  } else {
    // Cross-column: bezier with control point at midpoint + vertical offset
    const midX = (sx + tx) / 2
    const midY = (sy + ty) / 2
    const arcHeight = Math.min(colDist * 15, 60)
    ctx.quadraticCurveTo(midX, midY - arcHeight, tx, ty)
  }
}
```

### Decision 3.3: 500+ 节点的标签与交互策略

| 条件 | 行为 |
|------|------|
| 默认 | 不渲染标签（500 个标签无论如何放不下） |
| zoom > 1.2 | 渲染当前可见区域内节点的标签 |
| hover 节点 | 渲染该节点及其直接邻居的标签 |
| 选中节点 | 渲染该节点标签（始终） |

---

## Layout Selection Logic (更新)

```
displayNodes.length ≤ 200   →  Tier 1: 同心圆布局 + 环约束碰撞
displayNodes.length 201-500 →  Tier 2: 增强力仿真 → 收敛 → 网格吸附
displayNodes.length > 500   →  Tier 3: 列式布局（确定性）

用户拖拽节点:
  Tier 1: 角度锁定（只能在圆环上旋转），释放后回到原位
  Tier 2: 自由拖拽，释放后吸附到最近空余格点
  Tier 3: 自由拖拽，释放后不吸附（保持拖拽位置）

搜索过滤后:
  以过滤后的节点数重新选取 Tier
  Tier 变更 → 完全重建布局
```

---

## Visual Design (all tiers)

延续极简扁平风格：

| 元素 | Tier 1 (≤200) | Tier 2 (200-500) | Tier 3 (500+) |
|------|--------------|-------------------|---------------|
| 节点 | 5 色扁平圆，内大外小 | 同左 | 同左，列内大小一致 |
| 边 | 极淡灰，同圈弧不同圈线 | 淡灰直线 | 淡灰贝塞尔曲线 |
| 标签 | 外向放置，始终显示 | zoom>0.5 或 hover 显示 | 仅 zoom>1.2 或 hover/选中 |
| 背景 | 纯白 | 纯白 + 淡色网格线 | 纯白 |

---

## Risks

| 风险 | 缓解 |
|------|------|
| 网格吸附后可能产生极端长边 | 步骤 5 的短暂微调力仿真解决 |
| 列式布局失去图结构空间语义 | 仅 500+ 使用；列按 degree 排，高 degree 列在左形成"重要性"流向 |
| Tier 切换视觉差异大 | 搜索过滤/展示全部导致节点数变化时，Tier 可能跨越阈值——接受，这是确定性重排 |
| 列式模式下边交叉仍然多 | 边渲染用极淡透明度（0.015），仅高亮时加深 |

## Rollback

- `USE_ORDERLY_LAYOUT = true` 开关（已有）
- `false` 时所有 Tier 回退到纯力仿真
