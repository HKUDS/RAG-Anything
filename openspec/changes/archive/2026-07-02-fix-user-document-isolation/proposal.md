## Why

新注册用户首次加载知识库页面时，会因为前端竞态条件与后端 `verify_kb_access` 权限校验逻辑缺陷，短暂看到不属于自己的知识库文档；刷新页面后恢复正常。这是一个数据隔离漏洞，根因是前后端配合中的时序问题和权限回退逻辑错误。

## What Changes

- **后端** `verify_kb_access`：修复权限校验逻辑 —— 当用户试图访问他人知识库且用户已有自己的知识库时，强制返回用户自己的知识库（而非透传他人的知识库），阻断跨用户数据泄露
- **前端** `KnowledgePage`：消除竞态条件 —— 在 `loadKBs()` 完成并确认 `activeKB` 属于当前用户之前，不再触发 `loadKBData()` 拉取文档数据
- **前端** `api.js`：移除模块级硬编码 `currentKB = 'default'`，改为空值并在请求前校验，避免以无效知识库名发起请求

## Capabilities

### New Capabilities
- `kb-access-control`: 知识库访问权限控制 —— 确保所有知识库 API 端点在任何条件下都按 `owner_id` 严格隔离数据，不因竞态或回退逻辑导致数据泄露

### Modified Capabilities
<!-- No existing specs cover KB access control or data isolation, so no modifications needed -->

## Impact

- **后端文件**: `server.py` — `verify_kb_access()` 函数（第 251–287 行）权限回退逻辑
- **前端文件**: `frontend/src/pages/KnowledgePage.jsx` — `activeKB` 初始状态和 `useEffect` 依赖时序
- **前端文件**: `frontend/src/utils/api.js` — `currentKB` 模块级状态和 `kbUrl()` 函数
- **安全影响**: 修复跨用户数据泄露漏洞（中危 —— 仅瞬时暴露，刷新后恢复，但恶意用户可通过直接 API 调用持续利用）
