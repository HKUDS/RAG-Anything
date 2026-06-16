## 1. 执行引擎 (workflow-execution)

- [x] 1.1 创建 `raganything/workflow_executor.py`：执行器基类 + 6 种节点执行器 + 拓扑排序 + 错误处理
- [x] 1.2 在 `server.py` 添加 `POST /api/workflows/{id}/run` 端点
- [x] 1.3 在 `server.py` 添加 WebSocket `/ws/workflow-run/{run_id}` 状态推送
- [x] 1.4 在 `server.py` 添加 `GET /api/workflows/{id}/runs` 历史列表
- [x] 1.5 在 `server.py` 添加 `GET /api/workflows/{id}/runs/{run_id}` 单次详情
- [x] 1.6 创建 `workflows/runs/` 目录存储运行记录

## 2. 运行时 UI (workflow-run-ui)

- [x] 2.1 WorkflowToolbar 添加 "▶ 运行" 按钮（有节点时显示）
- [x] 2.2 WorkflowNode.jsx 支持 `runStatus` 状态颜色渲染（蓝色=运行、绿色=完成、红色=失败 + pulse动画）
- [x] 2.3 创建 `WorkflowRunPanel.jsx`：底部可折叠输出面板（节点时间线 + 最终输出 + 历史切换）
- [x] 2.4 WorkflowPage 集成运行状态管理（handleRun + setNodes runStatus + handleSelectRun）
- [x] 2.5 WorkflowPage 运行历史列表 + 切换查看（下拉选择历史 run）

## 3. 验证

- [x] 3.1 Build 验证 — Vite build 9.12s 成功
- [x] 3.2 Python 验证 — 拓扑排序正确 + 6 执行器注册表完整
