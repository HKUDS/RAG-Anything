## 1. Backend: Fix `verify_kb_access` permission fallback

- [x] 1.1 修改 `server.py` 中 `verify_kb_access()` 函数（第 263–272 行）：当非管理员用户试图访问他人 KB 且已找到用户自己的 KB 时，返回 `user_kb` 而非透传原始 `kb`
- [ ] 1.2 验证后端逻辑：用 `curl` 模拟非管理员用户带 `?kb=他人KB` 参数请求 `/api/knowledge/documents`，确认返回用户自己的 KB 数据而非他人数据（需启动服务端后手动验证）

## 2. Frontend: Fix KnowledgePage race condition

- [x] 2.1 将 `KnowledgePage.jsx` 中 `activeKB` 初始状态从 `useState('default')` 改为 `useState(null)`
- [x] 2.2 新增 `kbsLoaded` 状态标志，在 `loadKBs()` 成功完成后设为 `true`
- [x] 2.3 修改 `loadKBData()` 的 `useEffect` 依赖，增加 `kbsLoaded` 条件门控：仅当 `kbsLoaded === true` 且 `activeKB !== null` 时才执行
- [x] 2.4 在 `loadKBs()` 中，当 `r.knowledge_bases` 为空且 `r.active` 不存在时，不设置 `activeKB`（保持 null），避免使用无效默认值

## 3. Frontend: Fix module-level `currentKB` default

- [x] 3.1 将 `api.js` 中 `let currentKB = 'default'` 改为 `let currentKB = ''`
- [x] 3.2 在 `request()` 函数中增加 `currentKB` 空值检查：当 `currentKB` 为空字符串时，跳过请求并返回模拟空数据（`{ documents: [] }` / `{ entities: [] }` 等），避免发起 `?kb=` 空参数请求

## 4. Integration verification

- [ ] 4.1 注册新用户并立即观察 KnowledgePage：确认首次加载显示空知识库（用户个人 KB），不闪现他人文档（需启动服务端后手动验证）
- [ ] 4.2 以已有 KB 的用户身份，手动 `curl` 带 `?kb=他人KB` 参数访问文档/实体/图谱 API，确认返回用户自己的数据（需启动服务端后手动验证）
- [ ] 4.3 以管理员用户身份，确认仍可正常访问所有用户的知识库（需启动服务端后手动验证）
- [ ] 4.4 确认现有用户切换 KB 功能不受影响（需启动服务端后手动验证）
