## 1. 重构状态管理 (核心修复)

- [x] 1.1 WorkflowPage 引入 `useNodesState`/`useEdgesState`/`useReactFlow`/`ReactFlowProvider`
- [x] 1.2 WorkflowCanvas 改为纯受控组件（接收 nodes/edges/onNodesChange/onEdgesChange/onConnect）
- [x] 1.3 删除 WorkflowCanvas 内的 useEffect 双向同步代码

## 2. 修复缩放和适应

- [x] 2.1 WorkflowPage 通过 `useReactFlow()` 实现 zoomIn/zoomOut/fitView
- [x] 2.2 工具栏按钮绑定真实方法

## 3. 修复 ID 和 Toast

- [x] 3.1 nodeTypes.js 的 createDefaultNode 使用 crypto.randomUUID()
- [x] 3.2 server.py 的 workflow ID 使用完整 UUID
- [x] 3.3 WorkflowPage showToast 添加 useEffect cleanup

## 4. 验证

- [x] 4.1 Build 验证 — Vite build 成功
- [x] 4.2 架构审查通过 — 状态管理从双向同步改为受控模式
