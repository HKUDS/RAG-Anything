## Why

当前 RRF 查询只返回文本内容，但知识库中文档往往包含图片（图表、截图、照片等），这些图片对理解答案至关重要。用户需要在看到文本回答的同时，看到最相关的图片，提升答案的完整性和可信度。

## What Changes

- RRF 检索完成后，从返回的 chunk 中提取图片路径
- 按 chunk 的 RRF 分数排序图片（分数越高的 chunk 中的图片越相关）
- 返回 Top-3 最相关图片（base64 编码），附带来源 chunk 信息
- `_aquery_rrf` 返回值从纯文本扩展为结构化字典 `{text, images}`
- 前端查询结果区域展示 Top-3 图片缩略图

## Capabilities

### New Capabilities

- `rrf-image-extraction`: RRF 查询结果自动附带 Top-3 相关图片

## Impact

- 修改: `raganything/query.py` — `_aquery_rrf` 返回结构化结果含图片
- 修改: `raganything/hybrid_search.py` — `ScoredChunk` 增加 `images` 字段
- 修改: `server.py` — 查询端点解析图片并返回给前端
- 修改: 前端 `QueryPage.jsx` / `AgentChatPage.jsx` — 展示图片
