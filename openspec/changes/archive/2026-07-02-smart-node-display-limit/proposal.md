## Why

当前知识图谱硬限制显示 100 个节点，对于拥有 1000+ 实体的大型知识库，用户无法看到完整图谱结构。需要改为按连接度智能排序 + 用户可控的全量展示，兼顾性能与可视性。

## What Changes

- **按连接度排序**：无搜索时，优先显示连接数最多的前 200 个节点（核心结构节点），而非随机截断
- **"展示全部"按钮**：图谱下方显示 "显示 200/N 个节点"，点击可无限制渲染全部节点（1000+ 时附带性能提示）
- **搜索保持无限制**：搜索时仍显示全部匹配节点 + 邻居（搜索本身就是筛选）

## Capabilities

### Modified Capabilities
- `knowledge-graph-search-ux`: 节点数量限制从固定 100 改为按连接度 Top-200 + "展示全部"可选
- `frontend-visualization`: 图谱渲染策略改为按连接度优先级显示

## Impact

- 修改文件：`frontend/src/pages/KnowledgeDetailPage.jsx`（~20 行）
- 修改文件：`openspec/specs/knowledge-graph-search-ux/spec.md`（delta）
- 无 API 变更，无后端影响
