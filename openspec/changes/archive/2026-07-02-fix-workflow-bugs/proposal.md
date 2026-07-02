## Why

DAG 工作流编排功能存在 8 个缺陷，核心架构问题导致画布无法正常工作：双向状态同步死循环、缩放/适应按钮无响应、加载工作流不渲染、节点 ID 碰撞。

## What Changes

- **重构状态管理**：将 `useNodesState`/`useEdgesState` 从 WorkflowCanvas 提升到 WorkflowPage，消除双向同步循环
- **修复缩放/适应按钮**：通过 `useReactFlow()` hook 实现 zoomIn/zoomOut/fitView
- **修复节点 ID**：使用 `crypto.randomUUID()` 替代 `Date.now()`
- **修复后端短 UUID**：使用完整 UUID
- **修复 Toast 内存泄漏**：添加 cleanup 函数

## Capabilities

### New Capabilities
<!-- None, pure bugfix -->

### Modified Capabilities
- `dag-canvas`: 修复状态同步架构、缩放、加载渲染
- `node-config-panel`: 修复配置更新与画布同步
- `workflow-persistence`: 修复存储 ID 碰撞

## Impact

- [WorkflowCanvas.jsx](frontend/src/components/workflow/WorkflowCanvas.jsx) — 重构，移除双向 useEffect 同步
- [WorkflowPage.jsx](frontend/src/pages/WorkflowPage.jsx) — 提升 ReactFlow hooks + useReactFlow
- [nodeTypes.js](frontend/src/components/workflow/nodeTypes.js) — crypto.randomUUID()
- [server.py](server.py) — 完整 UUID
