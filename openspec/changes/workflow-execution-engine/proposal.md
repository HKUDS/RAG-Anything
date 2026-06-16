## Why

工作流画布已具备完整的编排能力（拖拽节点、连线、配置、保存），但搭建好的工作流无法执行——用户画完管道图后没有"打开水龙头"的方式。需要增加执行引擎和运行时 UI，让工作流从"设计工具"变成"可运行的 RAG 管道"。

## What Changes

- **▶ 运行按钮**：工具栏增加"运行"按钮，点击后按拓扑排序依次执行所有节点
- **执行引擎**：后端解析工作流 DAG，按节点类型调用对应的执行器（复用现有 RAG 组件：文档解析、分块、嵌入、检索、LLM 调用）
- **实时状态展示**：节点颜色变化表示执行状态（白色=待执行、蓝色=运行中、绿色=完成、红色=失败）
- **输出面板**：底部可折叠面板，展示最终输出内容和中间结果
- **运行历史**：保存每次执行的日志和结果，可回溯查看
- **执行 API**：`POST /api/workflows/{id}/run` + WebSocket 推送状态

## Capabilities

### New Capabilities
- `workflow-execution`: 工作流执行引擎 — 拓扑排序调度、节点执行器注册、错误处理
- `workflow-run-ui`: 运行时 UI — 节点状态变色、运行按钮、输出面板、历史记录

### Modified Capabilities
<!-- None, pure new functionality -->

## Impact

- **新增**：`raganything/workflow_executor.py` — 执行引擎
- **新增**：`server.py` 中的 WebSocket `/ws/workflow/{run_id}` + REST API
- **修改**：[WorkflowPage.jsx](frontend/src/pages/WorkflowPage.jsx) — 运行按钮 + 状态管理
- **修改**：[WorkflowNode.jsx](frontend/src/components/workflow/WorkflowNode.jsx) — 状态颜色
- **新增**：[WorkflowRunPanel.jsx](frontend/src/components/workflow/WorkflowRunPanel.jsx) — 输出面板
- **无破坏性变更**
