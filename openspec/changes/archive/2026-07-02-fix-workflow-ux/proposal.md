## Why

工作流画布在用户走查中发现 10 个体验缺陷，其中 3 个致命问题（无确认的数据丢失、无未保存标识、无快捷键）导致用户在日常使用中感到不安全和不高效。

## What Changes

- **数据安全**：新建/加载前检测未保存修改 → 确认弹窗；删除工作流 → 确认弹窗
- **快捷键**：Ctrl+S 保存、Ctrl+Z/Y 撤销/重做、Delete 删除、Escape 关闭面板
- **Handle 交互**：增大到 12px、hover 时放大到 16px + 发光效果
- **空状态引导**：画布无节点时显示 "从左侧拖入节点开始编排" 提示
- **面板优化**：缩小到 260px、Esc 关闭、点击画布空白关闭
- **缩放比例显示**：工具栏显示百分比
- **小地图优化**：无节点时隐藏

## Capabilities

### New Capabilities
<!-- None, pure UX enhancement -->

### Modified Capabilities
- `dag-canvas`: 增强交互（handle大小、快捷键、撤销/重做、拖拽预览、空状态）
- `node-config-panel`: 面板交互优化（Esc关闭、自适应宽度）
- `workflow-persistence`: 数据安全增强（确认弹窗）

## Impact

- [WorkflowCanvas.jsx](frontend/src/components/workflow/WorkflowCanvas.jsx)：handle样式、空状态、撤销/重做
- [WorkflowPage.jsx](frontend/src/pages/WorkflowPage.jsx)：快捷键、确认弹窗、面板Esc
- [WorkflowNode.jsx](frontend/src/components/workflow/WorkflowNode.jsx)：handle增大+hover效果
- [WorkflowToolbar.jsx](frontend/src/components/workflow/WorkflowToolbar.jsx)：缩放比例显示
- [NodeConfigPanel.jsx](frontend/src/components/workflow/NodeConfigPanel.jsx)：宽度优化
