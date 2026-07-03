## Why

知识图谱可视化存在 6 个严重影响用户体验的问题：搜索无结果时静默消失、节点数量限制不一致、删除边后侧边栏信息陈旧、SVG 高度浪费空间、D3 错误全被静默吞噬、以及两套图谱实现各自存在死代码。这些问题在之前的探索审查中被发现，需要系统性修复以提升知识库功能的可用性和专业感。

## What Changes

### KnowledgeDetailPage（知识库详情页图谱） — 5 项修复

- **搜索空结果状态**：当 `graphSearch` 过滤掉所有节点时，显示"无匹配实体"提示，而非空白 SVG
- **节点数量限制一致化**：统一搜索/非搜索场景的节点上限策略，搜索时同样应用上限并告知用户截断情况
- **删除边后刷新侧边栏**：删除关系时同步清除 `nodeDetails` 和 `graphNodeDetail` 状态，让侧边栏立即反映最新数据，而非显示陈旧信息
- **SVG 高度自适应**：将固定 420px 改为容器高度动态计算，充分利用 `h-[520px]` 的垂直空间
- **错误可见化**：移除 try-catch 的静默吞噬，将 D3 渲染错误通过 error 状态展示给用户，并提供重试按钮

### KnowledgeGraphD3（制造知识图谱页组件） — 3 项修复

- **移除死代码**：删除边标签的 textPath 创建逻辑（`.text('')`），注释已说明"标签禁用"
- **搜索邻居展开**：搜索结果自动包含匹配节点的直接邻居，与 KnowledgeDetailPage 行为一致
- **边标签位置更新**：如果未来启用边标签，`sim.on('tick')` 中已预留位置更新代码

### 跨组件 — 1 项清理

- **删除僵尸 entities tab 代码**：KnowledgeDetailPage 中 `activeTab !== 'entities'` 守卫的 useEffect 和注释标注 "deprecated" 的代码块

## Capabilities

### New Capabilities
- `knowledge-graph-search-ux`: 图谱搜索的空结果状态、结果数量提示和邻居展开
- `knowledge-graph-edge-management-ux`: 边删除后的侧边栏同步刷新和错误可见化

### Modified Capabilities
- `frontend-visualization`: 图谱容器高度改为响应式、搜索行为含邻居展开、去掉静默错误吞噬
- `knowledge-graph-interaction`: 边删除操作需同步更新侧边栏选中状态

## Impact

- 修改文件：`frontend/src/pages/KnowledgeDetailPage.jsx`（核心修改 ~60 行）
- 修改文件：`frontend/src/components/KnowledgeGraphD3.jsx`（删除死代码 ~10 行 + 新增邻居展开 ~10 行）
- 无 API 变更，无后端影响
- 无新增依赖
