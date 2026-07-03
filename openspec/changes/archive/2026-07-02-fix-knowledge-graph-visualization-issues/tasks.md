## 1. KnowledgeGraphD3 清理

- [x] 1.1 删除 `drawEdgeLabels()` 函数及 `edgeLabelsDrawn` 标志变量
- [x] 1.2 删除 `renderId` 参数（仅用于 edge path ID 去重，随 edge label 一起移除）
- [x] 1.3 搜索邻居展开：在 `filteredNodes` useMemo 中构建邻接表，搜索时将匹配节点的直接邻居加入结果集

## 2. KnowledgeDetailPage 搜索与节点限制

- [x] 2.1 统一节点上限为 100：无搜索 `displayNodes.slice(0, 100)`，有搜索同样截断
- [x] 2.2 截断提示：当 `displayNodes.length < totalNodes` 时，在图谱下方显示 "显示 N/M 个节点" 文字
- [x] 2.3 搜索空结果状态：`displayNodes.length === 0 && graphSearch` 时渲染空状态 overlay（"无匹配实体" + "清除搜索"按钮）

## 3. KnowledgeDetailPage 边删除与状态同步

- [x] 3.1 `handleDeleteEdge` 成功后清除 `nodeDetails`、`graphNodeDetail` 和 `selectedNode`，侧边栏回退到实体列表

## 4. KnowledgeDetailPage 布局与错误处理

- [x] 4.1 SVG 高度改为 `graphContainerRef.current?.clientHeight`，保留 `minHeight: 350`
- [x] 4.2 新增 `graphError` state，`drawGraph` catch 块设置错误消息
- [x] 4.3 渲染 error overlay：复用现有 AlertCircle + 错误描述 + 重试按钮模式
- [x] 4.4 删除废弃的 entities tab useEffect（`activeTab !== 'entities'` 守卫，永远不执行）
