## Context

`KnowledgeDetailPage.drawGraph()` 当前对无搜索场景硬截断前 100 个节点。大小知识库一视同仁，导致大库丢失核心结构节点（排在数组末尾的高连接度节点可能被截掉）。

## Goals / Non-Goals

**Goals:**
- 无搜索时按连接度（`degree`）降序排列，优先显示核心节点
- 用户可一键切换为全量渲染
- 搜索时不受限制

**Non-Goals:**
- 不改 KnowledgeGraphD3（制造知识图谱页）
- 不引入虚拟化或 WebGL 渲染

## Decisions

### Decision 1: Top-200 按 degree 降序

**选择**：无搜索时 `displayNodes.sort((a,b) => (b.degree||0) - (a.degree||0)).slice(0, 200)`

**理由**：degree 已在 `loadKBData` 中计算完成，零额外开销。高连接度节点是图谱的骨架结构，孤立节点即使被截断也不影响核心拓扑。

**默认 200**：比之前的 100 翻倍，覆盖中型知识库的全部节点。对大库既能展示核心结构，又不至于卡顿。

### Decision 2: useState 控制全量模式

**选择**：新增 `showAllNodes` state，点击"展示全部"时设为 true，此时跳过 Top-200 截断。按钮旁显示性能警告。

```jsx
{!showAllNodes && totalNodes > 200 && (
  <button onClick={() => setShowAllNodes(true)}>
    显示全部 {totalNodes} 个节点
    {totalNodes > 500 && '（性能可能下降）'}
  </button>
)}
```

**理由**：用户主动选择，知道代价。状态在 tab 切换时重置。

### Decision 3: 搜索时保持无限制

**选择**：`graphSearch` 非空时不应用 Top-200 截断。

**理由**：搜索是用户主动筛选，结果集通常远小于全量。邻居展开后也不应超过几百个。

## Risks / Trade-offs

- **[性能] 1000+ 全量渲染**：D3 仿真需 15-30 秒稳定，期间 UI 可能卡顿。→ "展示全部"按钮旁显示性能警告，用户知情选择。
- **[连接度偏差] degree 排序**：新导入的文档实体 degree 可能偏低，被截断。→ "展示全部"提供补救路径。
