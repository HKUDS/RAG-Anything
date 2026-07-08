## Context

当前 RAG-Anything 在知识库文档列表页 (`KnowledgeDetailPage.jsx`) 的"分块"列只展示一个数字（第 773 行 `{doc.chunks}`），用户无法查看每个切块的具体内容。后端已有完整的 chunk 存储（LightRAG `text_chunks` KV 存储 + `doc_status.chunks_list`），但缺少一个 API 端点将 chunk 详情暴露给前端。

项目中已有类似抽屉面板模式（文档详情抽屉，第 1007-1042 行）和图片服务端点（`GET /api/files/image`），可直接复用。

### 约束
- UI: 纯 Tailwind CSS + 自定义 `@layer components` 设计系统，无第三方组件库
- 图标: lucide-react
- 动画: framer-motion
- 认证: 需传递有效 token，图片标签需 `?token=xxx` 绕过 header 认证

## Goals / Non-Goals

**Goals:**
- 后端新增 `GET /api/knowledge/documents/{doc_id}/chunks` 返回文档所有 chunk 的排序详情
- 前端"分块"数字变为可点击按钮
- 右侧抽屉面板展示 chunk 列表，支持展开/折叠和文本搜索过滤
- 多模态块显示类型图标和缩略图（利用已有 `/api/files/image` 端点）

**Non-Goals:**
- 不提供 chunk 内容的编辑/修改功能
- 不更改任何切分策略或 chunk 存储格式
- 不修改 LightRAG 内部 chunk 处理逻辑
- 不提供批量导出 chunk 功能
- 不做语义搜索（v2）

## Decisions

### D1: API 设计 — 单个端点返回全部 chunk

**选择**: `GET /api/knowledge/documents/{doc_id}/chunks` 一次返回所有 chunk，前端做排序和过滤。

**替代方案**: 分页 API + 后端搜索。拒绝理由：大多数文档 < 50 个 chunk，单次请求足够；客户端过滤更灵活；避免服务端搜索复杂度。

### D2: 媒体路径解析策略

**选择**: 后端解析 chunk `content` 文本中的 `Image Path:` / `Table Image Path:` 行，提取路径作为 `media_path` 字段返回。同时检查是否配置了 `RAGANYTHING_PUBLIC_ASSET_BASE_URL`，如有则额外计算 `media_url` 字段。

**规则**:
- 成功提取且文件存在 → `media_path` = 绝对路径字符串
- `media_url` 优先（公网 URL），fallback 到 `/api/files/image?path=...&token=...` 端点
- 无媒体路径 → `media_path` = null，前端不渲染缩略图
- 路径为空或文件不存在 → `media_path` = null

### D3: 前端组件结构 — 内联抽屉，不抽独立文件

**选择**: 在 `KnowledgeDetailPage.jsx` 中直接实现分块详情抽屉，不创建独立组件文件。

**理由**: 现有文档详情抽屉（第 1007 行）也是内联实现；状态管理简单（一个 `selectedChunkDoc` state + `chunksData` state）；单文件改动最小。如果后续其他地方也需要此组件，再抽离。

### D4: 展开/折叠策略

**选择**: 第一块默认展开（`expandedChunks` 初始化为 `{0: true}`），其余折叠。提供"全部展开"和"全部折叠"按钮。

**实现**: `useState` 维护 `{[chunkOrderIndex]: boolean}` 映射，按钮设置全部为 `true`/`false`，过滤后列表的索引不参与展开状态。

### D5: Token 认证 — 图片端点复用

**选择**: 生成一个短期 token（使用已有认证系统的 token），附加到图片 URL 的 `?token=xxx` 参数。

**理由**: 已有 `/api/files/image` 端点支持 `?token=xxx` 绕过 Authorization header 认证（HTML `<img>` 标签无法设置 header）。前端从当前登录态获取 token（`localStorage` 或 context）直接拼接 URL。

## Risks / Trade-offs

- **[性能] 大文档 200+ chunk 一次性加载** → 缓解：前端虚拟列表（可选，v1 不做）；大多数文档 < 50 chunk，实测无问题
- **[安全] 图片路径泄露** → 缓解：`/api/files/image` 已有路径安全验证（限制在项目目录内）；`media_path` 仅对认证用户返回
- **[一致性] doc_status.chunks_list 与实际 text_chunks 不一致** → 缓解：API 中做防御性查询，chunk_id 不存在时跳过而非报错
- **[Token 过期] 图片 token 过期导致缩略图加载失败** → 缓解：前端捕获图片 `onError` 事件，显示占位图标
