## Why

后端已完整实现文档原文件下载 API（`GET /api/knowledge/documents/{doc_id}/download`，支持认证、MIME 检测、HTTP Range、路径安全），但前端界面未暴露任何下载入口——用户在知识库上传文档后无法下载回原始文件。主要场景是视频文件（MP4/MOV 等），用户需要下载已上传的视频进行本地查看或二次处理。

## What Changes

- **后端**：下载端点 `GET /api/knowledge/documents/{doc_id}/download` 增加 `?token=xxx` query 参数认证回退（复用已有 `get_current_user_from_token`），使 `<a>` 标签和浏览器原生下载管理器可直接使用该端点
- **前端 — 知识库文档列表表格**：操作列添加下载按钮。对于有原始文件的文档（`file !== "?"`）显示下载按钮，无原始文件的文档（粘贴内容、URL 导入）隐藏下载按钮
- **前端 — 知识库文档列表表格**：文件名变为可点击的下载链接，点击触发原生浏览器下载
- **前端 — 文档详情面板**：底部添加下载操作按钮，方便用户在查看文档详细信息后直接下载
- **前端 — API 工具函数**：`downloadDocumentUrl()` 在构造 URL 时附加当前用户的 auth token

## Capabilities

### New Capabilities
- `document-download`: 从前端下载已上传到知识库的原始文件（含视频），支持表格按钮、可点击文件名、详情面板三种入口

### Modified Capabilities
<!-- No existing specs modified. -->

## Impact

| 影响层面 | 详情 |
|---------|------|
| 后端代码 | `raganything/routers/knowledge.py` — `download_document` 函数签名变更（添加 `token` 参数和 `get_optional_user`） |
| 前端代码 | `frontend/src/utils/api.js` — `downloadDocumentUrl` 增加 token 参数 |
| 前端代码 | `frontend/src/pages/KnowledgeDetailPage.jsx` — 表格操作列、文件名列、详情面板三处 UI 修改 |
| 新增依赖 | `lucide-react` 中的 `Download` 图标（项目已使用该图标库） |
| 破坏性变更 | 无。后端端点保持向后兼容（header 认证仍为首选） |
