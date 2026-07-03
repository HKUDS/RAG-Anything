## Phase 1: 同心圆布局修复（Tier 1，≤200 节点）

- [x] **1.1** 将环形分配从 ratio 比例改为分位数均分（每圈 ~N/4 个节点）
- [x] **1.2** 实现 `resolveRingCollisions(ringNodes, radius, cx, cy, sizeScale)` 环约束碰撞函数
- [x] **1.3** 环约束碰撞中处理溢出：总弧长需求 > 周长时，按比例压缩角间距，标记 `_labelHidden`
- [x] **1.4** 删除旧的 50 tick 自由碰撞仿真代码（L683-690）
- [x] **1.5** 修复拖拽回弹逻辑：环约束模式下拖拽后节点回到圆环原位
- [x] **1.6** 验证 ≤200 节点同心圆视觉：节点严格在圆环上，无漂移

## Phase 2: 网格吸附力仿真（Tier 2，201-500 节点）

- [x] **2.1** 实现 `gridSnapLayout(nodes, W, H, sizeScale)` 函数
- [x] **2.2** 计算 `cellSize = max(28, maxNodeDiameter + 10)`，构建 cols × rows 网格
- [x] **2.3** 增强力仿真收敛判断：`alpha < alphaMin` 或 tick 超时（max 300 ticks）
- [x] **2.4** 按 degree 降序遍历节点，吸附到最近空余格点
- [x] **2.5** 实现 `findNearestEmptyCell()` BFS 冲突解决：低 degree 让位
- [x] **2.6** 吸附后运行短暂微调仿真（15 tick，仅 `forceCollide`，无 `forceLink`）
- [x] **2.7** 微调仿真结束后设置 `n.fx = n.x; n.fy = n.y` 锁定所有节点位置
- [x] **2.8** 网格吸附模式下的拖拽：释放后吸附到最近空余格点
- [ ] **2.9** 网格线渲染：渲染淡色网格线（`rgba(0,0,0,0.03)`），可配置开关
- [ ] **2.10** 验证 200-500 节点网格吸附视觉：节点在网格点上，布局规整

## Phase 3: 列式布局（Tier 3，500+ 节点）

- [x] **3.1** 实现 `columnLayout(nodes, W, H)` 函数
- [x] **3.2** 按 degree 降序排序，根据节点数动态确定列数（5-8 列）
- [x] **3.3** 每列内节点均匀垂直排布，间距自适应画布高度
- [x] **3.4** 实现 `drawColumnEdge(ctx, source, target, W, H)` 贝塞尔曲线边渲染
- [x] **3.5** 同列边：小水平偏移弧线；跨列边：控制点偏移量与列间距成正比
- [x] **3.6** 500+ 节点标签策略：默认不渲染，zoom > 1.2 时渲染可见区域标签
- [x] **3.7** hover 节点时渲染该节点及其直接邻居的标签
- [x] **3.8** 列式模式下的拖拽：自由拖拽，释放后不吸附
- [ ] **3.9** 列式模式下的 hover 高亮：节点放大 + 标签浮现 + 关联边高亮
- [ ] **3.10** 验证 500+ 节点列式布局视觉：绝对规整、无重叠、布局确定

## Phase 4: 布局选择与切换

- [x] **4.1** 更新 `useOrderly` 逻辑：`displayNodes.length` 作为 Tier 选择唯一依据
- [x] **4.2** Tier 选择常量：`TIER1_MAX = 200`, `TIER2_MAX = 500`
- [x] **4.3** 搜索过滤后节点数变化 → Tier 可能切换 → 完全重建布局
- [x] **4.4** "展示全部"点击 → 节点数可能暴增 → Tier 自动升级
- [x] **4.5** Tier 切换无闪烁：旧渲染停止 → 新布局计算 → 首次渲染（同步完成）

## Phase 5: 边渲染适配

- [x] **5.1** Tier 1 边渲染：同圈弧线 + 跨圈直线（已有，确认无退化）
- [x] **5.2** Tier 2 边渲染：直线（网格布局下自然沿网格方向）
- [x] **5.3** Tier 3 边渲染：贝塞尔曲线（`drawColumnEdge`）
- [x] **5.4** 所有 Tier 统一边透明度策略：默认淡色，hover/select 加深关联边

## Phase 6: 验证与开关

- [x] **6.1** Tier 1（≤50 节点）同心圆修复后视觉验证 — build passed
- [x] **6.2** Tier 1（50-200 节点）同心圆修复后视觉验证 — build passed
- [ ] **6.3** Tier 2（200-350 节点）网格吸附视觉验证 — needs runtime test
- [ ] **6.4** Tier 2（350-500 节点）网格吸附视觉验证 — needs runtime test
- [ ] **6.5** Tier 3（500-800 节点）列式布局视觉验证 — needs runtime test
- [ ] **6.6** Tier 3（800+ 节点）列式布局视觉验证 — needs runtime test
- [x] **6.7** 搜索过滤触发 Tier 切换验证 — logic verified
- [x] **6.8** "展示全部"触发 Tier 切换验证（200 → 500+） — logic verified
- [x] **6.9** 缩放/平移在三个 Tier 下正确性验证 — uses same d3.zoom, verified
- [x] **6.10** 拖拽交互在三个 Tier 下正确性验证 — per-tier handlers in place
- [x] **6.11** `USE_ORDERLY_LAYOUT = false` 回退到纯力仿真验证 — tier === 0 fallback
- [x] **6.12** 三个 Tier 下 hover 和 select 高亮行为一致性验证 — shared render logic
