## Context

RAG-Anything 的下载功能目前是半完成状态：

- **后端**：`GET /api/knowledge/documents/{doc_id}/download` 已完整实现——认证、KB 访问控制、MIME 检测、HTTP Range 支持、路径安全。但仅支持 `Authorization: Bearer` header 认证。
- **前端**：`api.js` 中定义了 `downloadDocumentUrl()` 函数，但未被任何组件引用。文档列表页面（`KnowledgeDetailPage.jsx`）没有下载入口。
- **参考实现**：`/api/files/image` 端点已支持 `?token=xxx` 双模式认证（header + query param），由 `get_optional_user` + `get_current_user_from_token` 实现。

主要场景是视频文件——用户上传视频到知识库后需要下载回原始文件，大文件场景需要浏览器原生下载管理器（进度条、断点续传），这要求使用 `<a>` 标签而非 JS fetch。

## Goals / Non-Goals

**Goals:**
- 在文档列表表格操作列、文件名列、详情面板三处提供下载入口
- 后端支持 `?token` query 参数认证，使 `<a>` 标签可直接触发下载
- 对无原始文件的文档（粘贴内容、URL 导入）合理隐藏下载入口
- 复用已有 `get_current_user_from_token` 和 `Download` 图标，最小化新增代码

**Non-Goals:**
- 批量下载（含 ZIP 打包）
- 下载历史/统计
- 文件格式转换
- 可访问性（屏幕阅读器等）

## Decisions

### Decision 1: `<a>` 标签 + `?token` vs JS fetch + blob

**选择：`<a>` 标签 + `?token` query 参数**

| 方案 | `<a>` + token | JS fetch + blob |
|------|--------------|-----------------|
| 大文件（视频） | ✅ 浏览器原生下载管理器 | ❌ 全部加载到内存 |
| 进度显示 | ✅ 浏览器原生进度条 | ⚠️ 需手动实现 |
| 断点续传 | ✅ 浏览器支持 | ❌ 不支持 |
| 实现复杂度 | ✅ 后端 ~5 行，前端纯 HTML | ⚠️ 前端 ~20 行 async 逻辑 |
| 内存占用 | ✅ 流式写入磁盘 | ❌ Blob 全部在内存 |

理由：视频是主要场景，浏览器原生下载体验远优于 JS blob。

### Decision 2: 文件名可点击 vs 仅有按钮

**选择：两者都做——可点击文件名 + 独立下载按钮**

理由：用户反馈希望两种方式都有。文件名可点击是文件管理器的常见模式（Google Drive、Dropbox），独立按钮提供明确的操作入口。两种方式不互斥，实现上复用同一个 URL。

### Decision 3: 无文件文档的判断依据

**选择：前端通过 `doc.file === "?"` 判断**

`list_documents` 返回的文档对象中，`file` 字段在 `file_path` 缺失时回退为 `"?"`（`knowledge.py:564`）。这是一个可靠但不够优雅的指示器。不引入新字段（如 `has_file` boolean）以避免 API schema 变更。

### Decision 4: 详情面板下载按钮位置

**选择：放在元数据列表下方，作为半宽主按钮**

```
┌──────────────────────────┐
│  文档详情            [✕] │
│  ┌─────────────────────┐ │
│  │ 文件名    video.mp4 │ │
│  │ 状态      ✅ 已完成  │ │
│  │ ...                │ │
│  └─────────────────────┘ │
│  ┌─────────────────────┐ │
│  │  📥 下载原始文件     │ │  ← 新增
│  └─────────────────────┘ │
└──────────────────────────┘
```

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| `?token` 暴露在 URL 中，可能被浏览器历史/日志记录 | Token 已存在于前端内存中（localStorage）；与 image 端点一致的暴露面；可考虑短期 token 过期（非本变更范围） |
| `doc.file === "?"` 判断可能误判 | 后端 `file_path` 缺失时确定返回 `"?"`；如有假阳性可后续在后端加 `has_file` boolean |
| 文件名作为 `<a>` 标签可能影响表格布局 | 保持 truncate + max-width 样式，与当前纯文本一致 |

## Open Questions

<!-- 无 -->
