## 1. 导航与数据加载

- [x] 1.1 `KnowledgePage.switchKB` 立即 `navigate`，预取转后台；移除 `openingKB`/`openRequestGateRef` 阻塞机制及其引用（保留 hover 预取与 saveData 守卫）。
- [x] 1.2 `KnowledgeDetailPage` 挂载只请求核心数据（documents/stats 走 prefetch 缓存、upload tasks）；entities/graph 请求移到图谱 tab 激活时触发。
- [x] 1.3 新增 `utils/lazyD3.js`（`loadD3()` 缓存 `import('d3')` promise），替换 `KnowledgeDetailPage` 静态 d3 导入，在 `drawGraph`/缩放/力导向等调用点 `await loadD3()`。
- [x] 1.4 图谱 tab 增加 loading/ready/error 状态：实体列表与图谱区域加载中显示骨架，不显示“暂无实体数据/暂无关系”；首载失败提供重试。
- [x] 1.5 图谱 tab 激活后（含切回）触发一次 entities/graph 刷新；`allEntityNames` 等派生仅在有数据后更新。

## 2. 轮询收敛

- [x] 2.1 将 8s `force:true` 全量轮询改为 15s 可见性+任务感知循环：循环内刷新 `getUploadTasks()` 作为门控，存在非终态任务才轮询核心数据，全部终态时执行最后一次 `loadKBData` 后停止。
- [x] 2.2 `document.hidden` 时停止轮询，恢复可见立即执行一次检查/刷新；图谱数据仅图谱 tab 激活时随轮询刷新。
- [x] 2.3 抽纯函数 `shouldPollCoreData({ visible, hasActiveUploads, activeTab })` 与终态转换判定，并补单元测试。

## 3. 空态门控与骨架

- [x] 3.1 `AgentsPage` 增加 loading 门控：加载中显示骨架，加载完成后才可能显示“这里还没有智能体”。
- [x] 3.2 `MonitorPage` “暂无已缓存的知识库实例”与 `AgentChatPage` “暂无对话”增加 loading 门控。
- [x] 3.3 `KnowledgePage` 在 `!kbsLoaded` 时显示列表骨架。
- [x] 3.4 骨架组件遵循既有 `PageSkeleton` 模式并带 `aria-busy`；尊重 `prefers-reduced-motion`。

## 4. 首屏与构建

- [x] 4.1 新增依赖 `@fontsource/inter`（400/500/600 + italic 400）与 `@fontsource/jetbrains-mono`（400/500），在入口导入；删除 `index.html` 的 Google Fonts 外链与 preconnect。
- [x] 4.2 从 `App.jsx` 移除 framer-motion：toast/用户菜单/启动加载改用 CSS 过渡；页面懒加载 chunk 内保留 framer-motion。
- [x] 4.3 `vite.config.js` manualChunks 增加 d3 独立 vendor chunk；核对 charts-vendor 仅随 MonitorPage。
- [x] 4.4 侧栏/顶栏导航链接 hover 预取目标路由懒加载 chunk（`navigator.connection.saveData` 守卫，仅可见且有权限项）。
- [x] 4.5 修复 `request()`/`fetchJson()` 中重复的 `headers` 键（顺手清理）。
- [x] 4.6 保留 `key={location.pathname}` 于外层 route-surface 是有意取舍（保住 SuspenseWithTimeout 超时兜底），不再强制重挂载。

## 5. 部署与启动

- [x] 5.1 `nginx.conf`：`/assets/` 加 `Cache-Control: public, max-age=31536000, immutable`；`/index.html` 加 `no-cache`；两个新 location 内重复声明全部安全头（nginx `add_header` 不继承）。
- [x] 5.2 `main.jsx`：先渲染，再后台 `synchronizeSystemDataEpoch()`；返回变化时立即 `location.reload()`（不等 15s monitor 心跳）。

## 6. 验证与收尾

- [ ] 6.1 实现前先跑干净 `npm --prefix frontend run build` 生成基线，记录 `dist/assets` 关键链（入口+react/router/icons vendor+css）体积。（未在实现前完成；当前仅有旧 `dist` 快照 563,307 B，非同源干净基线）
- [x] 6.2 为 stats TTL 键控缓存与图谱按需加载状态（`utils/globalStatsCache.js`、`utils/knowledgeDetailGraphState.js`）补单元测试（测试文件必须位于 `src/utils/`）。
- [ ] 6.3 `npm run test:unit` 全绿（81 项既有 + 新增）；`npm run build` 通过；关键链 raw 体积下降 ≥20%；`dist/index.html` 无 `fonts.googleapis.com`。（单测 101/101、生产构建、外链字体检查已通过；启动直接链 483,290 B，相对旧快照下降 14.2%，尚不能证明 ≥20%）
- [x] 6.4 `git diff --check` 通过；OpenSpec 校验（`openspec validate` 或等效）通过。
- [x] 6.5 更新 `PROJECT_SUMMARY.md`（当前状态 + 近期任务记录，遵守 ≤350 行/30KB 与近期任务 ≤15 条约束），并过 `scripts/check_project_summary.py`。
