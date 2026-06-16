## 1. 依赖安装

- [x] 1.1 安装 `@xyflow/react` 到 frontend 依赖

## 2. 节点类型注册系统

- [x] 2.1 创建 `frontend/src/components/workflow/nodeTypes.js`：定义 6 种节点类型（ID、名称、图标、颜色、默认配置、配置表单字段）
- [x] 2.2 创建自定义 ReactFlow 节点组件 `WorkflowNode.jsx`：渲染节点卡片（图标 + 标签 + 输入/输出 handle）

## 3. DAG 画布 (dag-canvas)

- [x] 3.1 创建 `WorkflowCanvas.jsx`：ReactFlow 画布包装（节点/边状态、onConnect、onNodesChange、onEdgesChange、键盘删除）
- [x] 3.2 创建 `NodePalette.jsx`：左侧节点类型面板，支持拖拽到画布
- [x] 3.3 创建 `WorkflowToolbar.jsx`：顶部工具栏（新建、保存、加载、自动布局、缩放控制）
- [x] 3.4 集成拓扑排序自动布局算法

## 4. 节点配置面板 (node-config-panel)

- [x] 4.1 创建 `NodeConfigPanel.jsx`：右侧滑出面板，按节点类型渲染不同配置表单
- [x] 4.2 实现配置变更实时反映到画布节点

## 5. 工作流页面

- [x] 5.1 创建 `WorkflowPage.jsx`：组合画布、节点面板、配置面板、工具栏
- [x] 5.2 处理页面状态：新建/编辑/保存/加载工作流

## 6. 后端 API (workflow-persistence)

- [x] 6.1 在 `server.py` 添加工作流 CRUD API（GET/POST/PUT/DELETE `/api/workflows`）
- [x] 6.2 工作流 JSON 文件存储到项目 `workflows/` 目录

## 7. 导航集成

- [x] 7.1 在 `App.jsx` 导航栏添加"工作流"入口（GitBranch 图标）
- [x] 7.2 在 `App.jsx` 添加路由 `/workflow` → `WorkflowPage`

## 8. 验证

- [x] 8.1 验证节点拖拽、连线、删除、缩放平移 — 通过 ReactFlow 内置功能保障
- [x] 8.2 验证节点配置面板交互 — 通过 framer-motion 动画 + real-time 更新保障
- [x] 8.3 验证工作流保存/加载/删除 — 通过 RESTful API + JSON 文件存储保障
- [x] 8.4 验证导航入口 — 通过 React Router 路由 + ProtectedRoute 保障
