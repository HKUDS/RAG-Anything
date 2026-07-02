## 1. RRF 图片提取核心

- [ ] 1.1 在 `_aquery_rrf` 中实现图片提取逻辑：遍历 chunk → 正则提取图片路径 → 按 RRF 分数排序 → 去重 Top-3
- [ ] 1.2 将 `_aquery_rrf` 返回值从 `str` 改为 `{text: str, images: List[dict]}`
- [ ] 1.3 图片 base64 编码（复用 `encode_image_to_base64`）
- [ ] 1.4 处理图片文件不存在的情况（跳过，不报错）

## 2. 调用方适配

- [ ] 2.1 `server.py` 智能体流式端点解析新的结构化返回值
- [ ] 2.2 `QueryMixin.aquery()` 中保持对 `_aquery_rrf` 返回值的兼容处理（提取 text 部分返回）
- [ ] 2.3 `SearchTool.execute()` (agentic_rag.py) 适配新返回格式

## 3. 前端展示

- [ ] 3.1 `QueryPage.jsx` 查询结果区展示图片缩略图
- [ ] 3.2 `AgentChatPage.jsx` 对话消息中展示图片缩略图
