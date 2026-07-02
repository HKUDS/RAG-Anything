# Tasks: 制造智能体 KB 选择器

## 1. 后端改造

- [x] 1.1 `server.py` 制造 API 端点（qa/dashboard/knowledge-graph）添加 `kb` 查询参数
- [x] 1.2 `_get_mfg_agent_components()` 根据 kb 参数动态创建 RAG 实例

## 2. 前端改造

- [x] 2.1 `ManufacturingAgentPage.jsx` 顶部添加 KB 选择器
- [x] 2.2 `ManufacturingDashboardPage.jsx` 顶部添加 KB 选择器
- [x] 2.3 所有制造 API 调用携带 `?kb=` 参数

## 3. 验证

- [x] 3.1 切换 KB 后制造智能体检索范围正确变更
