## Why

用户在知识库中上传文档后，只能看到"分块数"一个数字，无法查看每个切块的具体内容、分割边界、token 消耗和多模态处理结果。这使得用户无法验证切分质量、审计多模态内容处理是否正确，也无法评估 token 成本。需要提供一个分块详情面板，让用户能直观地查看每个 chunk 的完整信息。

## What Changes

- 文档列表页"分块"列的数字从纯文本改为可点击按钮，点击弹出右侧抽屉面板
- 新增后端 API `GET /api/knowledge/documents/{doc_id}/chunks` 返回文档的所有 chunk 详情
- 抽屉面板展示：统计摘要（总块数、总 token 数）、chunk 列表（序号、token 数、页码、内容预览、类型标签）
- 每个 chunk 可展开查看完整内容
- 多模态块（图片/表格/公式/视频）显示类型图标和缩略图（利用已有 `/api/files/image` 端点）
- 默认展开第一块，其余折叠；提供"全部展开/折叠"快捷按钮
- 提供客户端纯文本搜索过滤

## Capabilities

### New Capabilities
- `chunk-detail-view`: 文档切块详情查看 — 提供 API 获取单个文档的所有 chunk 详情，以及前端面板展示每个 chunk 的内容、token 数、页码、多模态类型和缩略图

### Modified Capabilities
<!-- No existing capability requirements are changing. -->

## Impact

| 层面 | 影响 |
|------|------|
| **API** | 新增 `GET /api/knowledge/documents/{doc_id}/chunks` |
| **前端** | KnowledgeDetailPage.jsx 分块列交互变更；新增分块详情抽屉组件 |
| **存储** | 只读访问 LightRAG text_chunks KV 存储和 doc_status |
| **依赖** | 复用已有 `GET /api/files/image` 图片服务端点；无新增依赖 |
