# Proposal: 制造智能体 KB 选择器

## Why

制造智能体当前硬编码连接到默认知识库 `rag_storage/`，但用户的实际文档上传在其他 KB（如 `rag_storage_111/`），导致制造智能体检索不到任何内容。需要让制造智能体页面独立选择知识库。

## What Changes

- **新增** 制造智能体页面 KB 选择器：独立于全局 KB 选择器，切换制造智能体的检索范围
- **改造** 制造 API 端点：`/api/manufacturing/qa`、`/api/manufacturing/dashboard` 等接受 `?kb=` 参数
- **改造** `_get_mfg_agent_components()`：根据 KB 参数动态创建 RAG 实例

## Capabilities

### New Capabilities

- `manufacturing-kb-selector`: 制造智能体独立 KB 选择。前端制造页面顶部显示 KB 下拉，切换后自动更新后端检索范围。

## Impact

- **修改**: `server.py`（制造 API 端点接受 kb 参数）、`frontend/src/pages/ManufacturingAgentPage.jsx`（添加 KB 选择器）、`frontend/src/pages/ManufacturingDashboardPage.jsx`（添加 KB 选择器）
- **新增**: `frontend/src/components/KBSelector.jsx`（KB 选择器组件）
