## 1. 后端 — 下载端点支持 ?token 认证

- [x] 1.1 修改 `download_document` 函数签名：添加 `token: Optional[str] = QueryParam(None)` 参数，将 `get_current_user` 替换为 `get_optional_user`，在 `current_user` 为 None 且 `token` 存在时调用 `get_current_user_from_token(token=token)` 回退认证
- [x] 1.2 验证：用 `curl` 测试 `?token=xxx` 参数认证（无 Authorization header）成功返回文件，无 token 返回 401

## 2. 前端 — API 工具函数更新

- [x] 2.1 修改 `api.js` 中 `downloadDocumentUrl` 函数：从 `localStorage` 读取 token（与 `authHeaders()` 使用相同 key），附加到 URL 的 `&token=xxx` 查询参数中

## 3. 前端 — 文档表格下载按钮

- [x] 3.1 在 `KnowledgeDetailPage.jsx` 顶部引入 `Download` 图标（来自 `lucide-react`）和 `downloadDocumentUrl`（来自 `../utils/api`）
- [x] 3.2 在表格操作列（第 687 行 `</button>` 之后、`<button ... title="详情"` 之前）添加下载按钮：仅当 `doc.file !== "?"` 时渲染，使用 `<a>` 标签包裹，`href={downloadDocumentUrl(doc.full_id)}`，样式与现有操作按钮一致（`btn-ghost text-xs py-1 px-2`）

## 4. 前端 — 文件名可点击下载

- [x] 4.1 修改文件名单元格（第 677 行）：当 `doc.file !== "?"` 时，将 `{doc.file}` 包裹在 `<a>` 标签中（`href={downloadDocumentUrl(doc.full_id)}`），保持现有 truncate 样式；当 `doc.file === "?"` 时保持纯文本渲染

## 5. 前端 — 文档详情面板下载按钮

- [x] 5.1 在详情面板的元数据列表（第 878 行 `</div>` 之前）之后、面板关闭前，添加下载按钮：仅当 `detailDoc.file !== "?"` 时渲染，使用 `<a>` 标签 `href={downloadDocumentUrl(detailDoc.full_id)}`，作为主操作按钮（`btn-primary` 样式，全宽，包含 `Download` 图标和文字"下载原始文件"）

## 6. 验证

- [x] 6.1 在前端 UI 中：上传一个 PDF 文件，确认文档列表中显示下载按钮、文件名可点击、详情面板有下载按钮，点击后浏览器成功下载
- [x] 6.2 上传一个视频文件（MP4），确认点击下载后浏览器使用原生下载管理器，支持进度条和断点续传
- [x] 6.3 粘贴一段文本内容（无文件），确认下载按钮和可点击文件名均不出现
- [x] 6.4 无认证状态下直接访问下载 URL，确认返回 401
