## Context

RAG-Anything 是一个多用户知识库 RAG 系统。知识库通过 `rag_storage_kb_meta.json` 中的 `owner_id` 字段实现多租户数据隔离。`verify_kb_access()` 函数是后端权限校验的核心依赖，被所有知识库作用域 API（文档、实体、图谱、统计等）使用。

当前存在两个配合缺陷导致数据隔离失效：

1. **后端权限回退逻辑错误**（`server.py:263-272`）：当用户已拥有自己的 KB 但试图访问他人 KB 时，`verify_kb_access` 在找到用户自己的 KB 后仍然返回请求的目标 KB（属于他人），而非重定向到用户自己的 KB 或抛出 403。
2. **前端竞态条件**（`KnowledgePage.jsx:346,413-414`）：`activeKB` 初始值为 `'default'`，`loadKBData()` 在 `loadKBs()` 完成前即触发，使首个 API 请求可能携带他人 KB 名称。当后端 `verify_kb_access` 因竞态找到刚自动创建的用户 KB 时，触发上述后端 Bug，导致跨用户数据返回。

触发场景：新用户注册后首次加载 KnowledgePage → `loadKBs()` 自动创建用户个人 KB → `loadKBData()` 几乎同时以 `kb=default` 调用 API → `verify_kb_access` 发现用户刚有了自己的 KB → 返回 `"default"` → 数据泄露。

## Goals / Non-Goals

**Goals:**
- 在任何时序下，非管理员用户都无法访问他人的知识库数据
- 消除前端竞态条件，确保 KB-scoped 请求始终使用经确认的用户所有 KB
- 保持管理员用户的完整访问能力
- 保持新用户自动创建个人 KB 的体验

**Non-Goals:**
- 不重构整体认证/授权架构（JWT + SQLite 方案保持不变）
- 不修改 KB 元数据结构（`owner_id` 模型保持不变）
- 不在本次变更中引入细粒度 RBAC 或 KB 共享功能

## Decisions

### 决策 1: `verify_kb_access` 发现用户已有 KB 时返回用户自己的 KB（而非抛 403）

**选择**: 静默重定向到用户自己的 KB（`return user_kb`）

**替代方案**:
- 方案 B: 抛出 403 Forbidden — 更严格但会在用户收藏旧链接或通过 URL 参数访问时破坏 UI 体验，且前端需要额外错误处理
- 方案 C: 不做修改，仅修复前端 — 不解决直接 API 调用的旁路攻击

**理由**: 静默重定向兼顾安全性与用户体验。用户试图访问不属于自己的 KB 时无感切换到自己的 KB，不需要额外的前端错误处理。恶意用户无法获取他人数据，合法用户不会因误操作看到错误页面。

### 决策 2: 前端使用 `kbsLoaded` 标志门控 `loadKBData`

**选择**: 在 KnowledgePage 中增加 `kbsLoaded` 状态，`loadKBs()` 完成后设为 `true`，`loadKBData()` 的 `useEffect` 依赖 `kbsLoaded` 而非仅依赖 `activeKB`

**替代方案**:
- 方案 B: 将 `loadKBData()` 调用内联到 `loadKBs()` 的 `.then()` 中 — 改动更小但耦合更紧，后续维护性差
- 方案 C: 使用 React Query 或 SWR 管理异步依赖 — 引入新依赖，过度工程化

**理由**: `kbsLoaded` 标志是一个轻量、明确的信号，清晰表达"KB 列表已就绪"的状态。改动小（约 5 行代码），不引入新依赖，不破坏现有轮询逻辑。

### 决策 3: `activeKB` 初始值改为 `null`，`currentKB` 模块变量改为空字符串

**选择**: `useState(null)` 初始化 `activeKB`，`let currentKB = ''` 初始化模块变量

**替代方案**:
- 方案 B: 保持 `'default'` 初始值，仅在前端加 if 判断 — 治标不治本，`'default'` 本身可能就是其他用户的 KB
- 方案 C: 使用 Jotai/Zustand 管理 KB 状态 — 引入新依赖

**理由**: 用"空"表示"未初始化"是最安全的默认状态。通过 null-check 门控可以确保任何基于过时默认值的请求都不会发出。改动最小，不引入新依赖。

### 决策 4: API 请求层增加 `currentKB` 空值校验

**选择**: 在 `kbUrl()` 或 `request()` 函数中，当 `currentKB` 为空字符串时跳过请求并返回空数据，而非向 `/api/knowledge/documents?kb=` 发起请求

**理由**: 作为纵深防御的最后一层——即使 UI 层出现逻辑疏漏，请求层也会拦截无效请求，确保后端不会收到无 KB 参数的调用。

## Risks / Trade-offs

- **[风险] 自动重定向可能掩盖用户的操作错误**: 用户手动输入 `?kb=other` 时不会收到错误提示，可能困惑为何看到的是自己的数据 → **缓解**: 对于合法用户，这比看到错误页面更好；可在后续版本中增加 Toast 提示
- **[风险] `active_kb` 全局变量仍为服务端共享状态**: 多用户并发时可能存在微小的状态不一致 → **缓解**: `active_kb` 仅用于 `/api/kb/list` 返回值的 `active` 字段（提示性），不参与权限判断，风险极低；未来可考虑从全局变量中移除
- **[权衡] 静默重定向 vs 显式报错**: 损失了错误可见性，换取了更好的用户体验 → **接受**: 安全优先，用户体验其次

## Migration Plan

1. **部署**: 修改后端 + 前端代码，无需数据迁移
2. **兼容性**: 前端向后兼容——旧版前端虽有竞态条件，但后端修复后即使触发竞态也会重定向到用户自己的 KB
3. **回滚**: 标准 git revert，无数据库 schema 变更或数据迁移依赖
4. **验证**: 注册新用户 → 观察首次页面加载 → 确认看到的是空知识库（而非他人数据）→ 手动尝试 `curl` 跨用户 KB 访问 → 确认返回自己 KB 数据
