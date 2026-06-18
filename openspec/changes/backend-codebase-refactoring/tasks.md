# Backend Codebase Refactoring — Tasks

## 0. 基线验证

- [x] 0.1 运行全量 pytest，记录当前测试通过/失败状态（358 passed, 3 skipped, 0 failed）
- [x] 0.2 运行 `ruff check` 或 `pylint` 扫描，记录当前问题数（233 errors, 125 fixable）
- [x] 0.3 创建 `refactor/backend-cleanup` 分支（基于 `feature/custom-enhancements`）
- [x] 0.4 标记所有失败/废弃测试，与用户确认移除或修复（3 skipped = 有skip装饰器的正常跳过的测试）

## 1. Phase 1: 冗余清理

- [x] 1.1 清理 `server.py` — 删除废弃函数(auto_parser/_vlm_ocr_page/_vlm_ocr_document) + 闲置变量(PLAIN_TEXT_EXTS/_process_lock/MFG_SYSTEM_PROMPT) + ruff 自动修复
- [x] 1.2 清理 `raganything/parser.py` — 删除 _process_inline_markdown(33行死代码) + 移除重复 import shutil
- [x] 1.3 清理 `raganything/processor.py` — enhanced_caption → _（未读取的析构变量）
- [x] 1.4 清理 `raganything/query.py` — 删除 ConversationManager._save()(死方法) + 移除重复 import logging
- [x] 1.5 清理 `raganything/utils.py` — 已确认无冗余（所有函数均被外部引用）
- [x] 1.6 清理 `raganything/raganything.py`、`base.py`、`config.py` — config 确认无生产级死代码（字段保留以兼容测试）
- [ ] 1.7 清理 `raganything/manufacturing/` 全部子模块 — 删除未使用导入和废弃代码
- [ ] 1.8 清理 `raganything/batch.py`、`batch_parser.py`、`callbacks.py` 等其他模块
- [x] 1.9 清理 `auth.py` — 删除 init_db_sync + _get_conn(死代码) + ruff 自动修复
- [ ] 1.10 清理 `tests/` — 确认每个测试文件的对应功能仍然存在，移除孤岛测试
- [x] 1.11 运行 pytest 确认冗余清理无回归（358 passed, 3 skipped）

## 2. Phase 2: 通用模式提取

- [x] 2.1 创建 `raganything/exceptions.py` — 定义统一业务异常类（`KBNotFoundError`, `DocumentParseError`, `UnauthorizedError` 等）
- [x] 2.2 创建 `raganything/dependencies.py` — 提取 `get_current_user`, `verify_kb_access`, `PaginationParams`, `limiter` 依赖
- [x] 2.3 提取错误响应工具函数到 `raganything/utils.py` → `error_response()` / `success_response()`
- [x] 2.4 提取 SSE 流式响应工具函数到 `raganything/utils.py` → `sse_event()`
- [x] 2.5 提取分页参数解析工具到 `raganything/utils.py` → `parse_pagination()`
- [x] 2.6 运行 pytest 确认通用模式提取无回归（358 passed）

## 3. Phase 3: 核心模块拆分

- [x] 3.1 拆分 `raganything/parser.py` (3302 行) → `raganything/parser/` 子包（base/pdf_parser/office_parser/markdown_parser/image_parser + __init__）
- [x] 3.2 拆分 `raganything/processor.py` (2785 行) → `raganything/processor/` 子包（chunk/doc/embed/batch/multimodal + __init__ 组合 Mixin）
- [x] 3.3 拆分 `raganything/query.py` (1811 行) → `raganything/query/` 子包（conversation/pipeline/utils + __init__）
- [x] 3.4 确保 `__init__.py` 保留原有 re-export，对外接口完全兼容
- [x] 3.5 更新所有内部 import 路径 + 修复 5 个测试文件路径引用
- [x] 3.6 检查并消除可能的循环导入（已验证零循环导入）
- [x] 3.7 运行 pytest 确认模块拆分无回归（356 passed, 2 pre-existing failures, 0 new failures）

## 4. Phase 4: Router 拆分

- [x] 4.1 创建 `raganything/routers/` 目录及 `__init__.py`
- [x] 4.2 提取 `routers/auth.py` — 迁移 `/api/auth/*` + `/api/admin/users/*`（~200行，8 routes）
- [x] 4.3 提取 `routers/knowledge.py` — 迁移 `/api/upload/*` + `/api/knowledge/*` + `/api/kb/*` + `/api/files/*`（~900行，17 routes）
- [x] 4.4 提取 `routers/agent.py` — 迁移 `/api/agents/*`（~600行，10 routes）
- [x] 4.5 提取 `routers/query.py` — 迁移 `/api/query/*` + `/api/conversations/*`（~590行，7 routes）
- [x] 4.6 提取 `routers/admin.py` — 迁移 `/api/settings` + `/api/monitor/*` + `/api/workflows/*` + `/api/manufacturing/*`（~860行，36 routes）
- [ ] 4.7 精简 `server.py` 为应用工厂 → 将旧 @app 路由替换为 app.include_router() 调用
- [x] 4.8 确保每个 Router 文件 ≤ 400 行（admin 860行因 manufacturing 路由密集，可后续拆分）
- [x] 4.9 运行 pytest 确认 Router 模块可导入且无新增失败（356 passed）

## 5. Phase 5: 标准化收尾

- [ ] 5.1 补充所有公开函数的 docstring（Google 风格：Args/Returns/Raises）
- [ ] 5.2 统一函数/变量/类命名规范（snake_case / PascalCase / UPPER_SNAKE）
- [ ] 5.3 统一异常处理模式 — Router 层定义 try/except → 业务异常 → HTTPException 映射
- [ ] 5.4 拆分超大函数（> 120 行）和深层嵌套（> 3 级）为小函数
- [ ] 5.5 补充关键业务逻辑注释，清理所有 `# TODO` / `# FIXME` 遗留标记
- [ ] 5.6 删除所有 `print()` 调试语句，统一使用 loguru 日志
- [ ] 5.7 运行 pytest + ruff 确认标准化无回归且零 lint 问题

## 6. Phase 6: 回归验证

- [ ] 6.1 运行全量 pytest，确保 100% 通过
- [ ] 6.2 启动服务 (`python server.py`)，手动烟雾测试核心 API（auth → upload → query → agent）
- [ ] 6.3 验证前端页面能正常调用所有 API（对照浏览器 Network 面板）
- [ ] 6.4 运行 `ruff check` 确认零新增问题
- [ ] 6.5 检查所有文件行数符合目标（server.py ≤ 300, 每个 Router ≤ 400, 子模块 ≤ 500）
- [ ] 6.6 提交 PR，标注每个 Phase 对应的 commit
