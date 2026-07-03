## 1. KnowledgeDetailPage 智能节点限制

- [x] 1.1 无搜索时按 `degree` 降序排列，Top-200 截断（替代固定 100 截断）
- [x] 1.2 新增 `showAllNodes` state，默认 false；搜索或 tab 切换时重置
- [x] 1.3 "展示全部"按钮：totalNodes > 200 时显示，点击设 `showAllNodes=true`，500+ 时附带性能警告
- [x] 1.4 `showAllNodes` 为 true 或搜索时，跳过 Top-200 截断
