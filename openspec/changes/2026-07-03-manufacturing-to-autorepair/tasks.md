# Tasks: manufacturing → autorepair 全量品牌重塑

## Phase 1: 后端 Python 模块 (12 tasks)

- [ ] 1.1 重命名目录 `raganything/manufacturing/` → `raganything/autorepair/`
- [ ] 1.2 更新 `raganything/autorepair/__init__.py` 内部引用
- [ ] 1.3 更新 `raganything/permissions.py` — `MANUFACTURING_READ/WRITE` → `AUTOREPAIR_READ/WRITE`
- [ ] 1.4 重命名 `raganything/routers/manufacturing.py` → `autorepair.py`，更新所有路由前缀、权限引用、函数名、模型类名
- [ ] 1.5 更新 `server.py` — import 路径、路由注册
- [ ] 1.6 更新 `raganything/services/kb_service.py` — 移除 manufacturing 特殊处理，通用化
- [ ] 1.7 更新 `raganything/services/pg_auth_repo.py` — 权限默认值
- [ ] 1.8 更新 `raganything/services/pg_kb_meta_repo.py` — KB domain 引用
- [ ] 1.9 更新 `raganything/agentic_rag/tools.py` — manufacturing 引用
- [ ] 1.10 更新 `raganything/routers/admin.py` — 权限引用
- [ ] 1.11 更新 `raganything/citation_parser.py` — manufacturing 引用
- [ ] 1.12 清理所有 `__pycache__/` 目录

## Phase 2: 前端重命名 (8 tasks)

- [ ] 2.1 重命名文件:
  - `ManufacturingAgentPage.jsx` → `AutoRepairAgentPage.jsx`
  - `ManufacturingDashboardPage.jsx` → `AutoRepairDashboardPage.jsx`
  - `ManufacturingKnowledgePage.jsx` → `AutoRepairKnowledgePage.jsx`
  - `ManufacturingKBSelector.jsx` → `AutoRepairKBSelector.jsx`
  - `useManufacturingKB.js` → `useAutoRepairKB.js`
- [ ] 2.2 更新 `AutoRepairAgentPage.jsx` — 组件名、所有中文文案、预设问法、tab标签、placeholder
- [ ] 2.3 更新 `AutoRepairDashboardPage.jsx` — 组件名、中文文案
- [ ] 2.4 更新 `AutoRepairKnowledgePage.jsx` — 组件名、中文文案、tab标签
- [ ] 2.5 更新 `AutoRepairKBSelector.jsx` — 组件名、弹窗文案、placeholder
- [ ] 2.6 更新 `useAutoRepairKB.js` — hook名、localStorage key `mfg_kb`→`autorepair_kb` + 旧key自动迁移
- [ ] 2.7 更新 `App.jsx` — lazy import路径、路由path、NAV标签、权限字符串
- [ ] 2.8 更新 `GCodeEditor.jsx` — 标签文案（可选：重命名为 OBDEditor）

## Phase 3: 数据库迁移 (1 task)

- [ ] 3.1 创建 `migrations/010_manufacturing_to_autorepair_permissions.sql` — 权限字符串批量替换

## Phase 4: 脚本与测试更新 (3 tasks)

- [ ] 4.1 更新 `test_mfg_api.py` — 重命名 + 引用更新
- [ ] 4.2 更新 `scripts/import_*.py` — manufacturing 引用
- [ ] 4.3 更新 `tests/test_agentic_reasoning.py` — manufacturing 引用

## Phase 5: 构建验证 (2 tasks)

- [ ] 5.1 前端 `vite build` 零错误
- [ ] 5.2 后端 `python -c "import raganything.autorepair"` 成功

---

**总计**: 26 tasks
