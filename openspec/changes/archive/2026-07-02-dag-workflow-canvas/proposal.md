## Why

RAG-Anything 缺少可视化工作流编排能力。目前的知识处理流程（文档解析 → 分块 → 嵌入 → 查询）是固定的线性管道，用户无法自定义处理步骤、组合不同节点、或设计复杂的数据流。引入 DAG 拖拽画布让用户以可视化方式编排 RAG 处理流程，显著降低复杂管道配置的门槛。

## What Changes

- **新增 DAG 拖拽画布页面**：使用 ReactFlow 实现节点拖拽、连线、缩放、平移的画布交互
- **新增节点配置面板**：点击节点弹出侧边面板，配置节点参数（如模型选择、阈值、提示词等）
- **新增节点类型注册系统**：预定义节点类型（文档输入、文本分割、嵌入、检索、LLM 回答、输出等），支持可扩展的节点注册
- **新增工作流 CRUD API**：保存/加载/删除/列表工作流定义，存储为 JSON
- **新增导航入口**：在顶部导航栏增加"工作流"链接
- **新增依赖**：`@xyflow/react`（ReactFlow v12）

## Capabilities

### New Capabilities
- `dag-canvas`: 可视化 DAG 画布 — 拖拽节点到画布、连线创建边、画布缩放平移、节点删除、自动布局
- `node-config-panel`: 节点配置面板 — 点击节点打开侧边面板，编辑节点参数，支持不同节点类型的专用配置表单
- `workflow-persistence`: 工作流持久化 — 后台 API 保存/加载/列表/删除工作流 JSON 定义

### Modified Capabilities
<!-- None - all new capabilities -->

## Impact

- **前端新增**：`WorkflowPage.jsx`、`components/workflow/*`（画布、节点、配置面板）
- **后端新增**：`server.py` 中添加 `/api/workflow/*` 路由
- **路由更新**：`App.jsx` 导航栏 + 路由表
- **新增依赖**：`@xyflow/react`
- **无破坏性变更**
