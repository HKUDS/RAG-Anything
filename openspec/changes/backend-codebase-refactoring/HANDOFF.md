# 后端重构 — 交接文档

> **目标 AI**：Claude Code / Cursor / GitHub Copilot  
> **分支**: `refactor/backend-cleanup`（基于 `feature/custom-enhancements`）  
> **测试基线**: 358 passed, 3 skipped（2 个预存失败：test_callbacks、testparser_wiring）  
> **约束**: 不得改动任何业务逻辑、API 契约、数据库操作

---

## 1. 已完成的工作

### Phase 0-2：清理 + 基础设施
- ruff 自动修复 124 项，手动删除 5 废弃函数 + 4 闲置变量 + 2 死方法
- 新建 `raganything/exceptions.py`（10 个业务异常类）
- 新建 `raganything/dependencies.py`（共享依赖：get_current_user、verify_kb_access、PaginationParams、limiter）
- `raganything/utils.py` 追加 4 个工具函数：`error_response()`、`success_response()`、`sse_event()`、`parse_pagination()`

### Phase 3：三大模块拆分（全部完成 ✅）

```
旧文件 → 新子包
───────────────────────────────────────────────
raganything/parser.py    (3302行) → raganything/parser/     (6 文件)
  ├── base.py             656行   Parser 基类 + MineruExecutionError + _IS_WINDOWS
  ├── pdf_parser.py       760行   MineruParser
  ├── office_parser.py    605行   DoclingParser
  ├── markdown_parser.py  662行   MarkerParser
  ├── image_parser.py     324行   PaddleOCRParser
  └── __init__.py         200行   get_parser() + register_parser() + CLI main()

raganything/processor.py (2785行) → raganything/processor/  (6 文件)
  ├── chunk_processor.py      442行   ChunkProcessorMixin
  ├── doc_processor.py       1199行   DocProcessorMixin
  ├── embed_processor.py      379行   EmbedProcessorMixin
  ├── batch_processor.py      212行   BatchProcessorMixin + register_background_task/get_pending
  ├── multimodal_processor.py 700行   MultimodalProcessorMixin
  └── __init__.py              30行   class ProcessorMixin(所有5个Mixin的复合)

raganything/query.py     (1811行) → raganything/query/      (4 文件)
  ├── conversation.py  282行   ConversationManager + ThreadSummary + ConversationContext
  ├── pipeline.py     1445行   QueryMixin（保留为完整类）
  ├── utils.py         152行   DEGRADED_CONTEXT_HINT + rerank_chunks + rewrite_query
  └── __init__.py       20行   Re-export 所有公共符号
```

**备份文件**：
- `raganything/parser.py.bak`
- `raganything/processor.py.bak`
- `raganything/query.py.bak`

### Phase 4：Router 模块（已创建，但未集成到 server.py）

```
raganything/routers/
├── __init__.py        空文件
├── shared.py          742行   所有共享状态 + 辅助函数（从 server.py 第6-812行提取）
├── auth.py            200行   8  routes（/api/auth/* + /api/admin/users/*）
├── knowledge.py       900行   17 routes（/api/upload/* + /api/knowledge/* + /api/kb/*）
├── agent.py           600行   10 routes（/api/agents/*）
├── query.py           590行   7  routes（/api/query/* + /api/conversations/*）
└── admin.py           860行   36 routes（/api/settings + /api/monitor/* + /api/workflows/* + /api/manufacturing/*）
```

**验证状态**：所有 5 个 Router 可独立导入，但 server.py 仍使用旧的 `@app.` 路由。

---

## 2. 待执行任务（按优先级排序）

### A. server.py 集成 Router（最高优先级，Risk⚠️）

**目标**：将 server.py 中所有 `@app.get/post/put/delete` 路由替换为 `app.include_router()` 调用，精简 server.py 至 <300 行。

**当前状态**：
- server.py 3666 行，包含 60+ 条 `@app.` 路由
- 5 个 Router 模块中的路由与 server.py 中的路由使用**相同的 API 路径**
- 不能同时存在新旧路由（FastAPI 会报重复路由错误）

**执行步骤**：

1. 在 server.py 第 210 行附近（`KB_META_FILE` 定义之后）添加 Router 导入和注册：
```python
# ── Router 注册 ─────────────────────────────────────
from raganything.routers.auth import router as auth_router
from raganything.routers.knowledge import router as knowledge_router
from raganything.routers.agent import router as agent_router
from raganything.routers.query import router as query_router
from raganything.routers.admin import router as admin_router

app.include_router(auth_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
```

2. 删除/注释掉 server.py 中所有旧的 `@app.` 路由装饰器及其处理函数。按以下行号范围操作：

| 旧路由块 | 行号范围 | 对应 Router |
|---------|---------|------------|
| Auth + Admin Users | 839-947 | auth.py |
| Files image | 818-832 | knowledge.py |
| Upload 全部 | 1215-1780 | knowledge.py |
| Knowledge CRUD | 1330-1720 | knowledge.py |
| KB list/create/switch/delete | 3188-3282 | knowledge.py |
| Agent CRUD | 1816-1896 | agent.py |
| Agent conversations | 1901-1972 | agent.py |
| Agent query stream | 1986-2376 | agent.py |
| Query + History | 2383-2744 | query.py |
| Query stream | 2782-2952 | query.py |
| Settings | 3007-3096 | admin.py |
| Monitor | 3100-3143 | admin.py |
| Health | 3146-3185 | admin.py |
| Workflows | 958-1208 | admin.py |
| WebSocket workflows | 1099-1131 | admin.py |
| WebSocket endpoint | 1568-1600 | admin.py |
| Manufacturing 全部 | 3290-3661 | admin.py |

3. 保留以下内容在 server.py 中（不移入 Router）：
   - 导入和配置（第 1-210 行）
   - CORS/SecurityHeaders/RequestSize 中间件（第 106-165 行）
   - validate_query_input（第 167 行）
   - SensitiveLogFilter（第 180-199 行）
   - kb_instances/active_kb/processing_tasks 等全局状态（第 202-208 行）
   - KB_META_FILE/QUERY_HISTORY_FILE（第 210-211 行）
   - get_current_user/get_admin_user/verify_kb_access（第 232-289 行）
   - load_kb_meta/save_kb_meta/kb_dir/get_kb（第 334-361 行）
   - create_rag（第 464-551 行）
   - _fix_stuck_doc_status（第 669 行）
   - _process_uploaded_file（第 691 行）
   - emit_progress/ws_broadcast/add_event（第 440-461 行）
   - Pydantic 模型类（第 555-583 行，部分可能重复）
   - if __name__ == "__main__"

4. **循环导入风险**：Router 模块使用 `from raganything.routers import shared`，而 shared.py 导入了 `raganything` 包的多个子模块。确保 server.py 中的 Router 导入放在所有 raganything 子模块导入**之后**。

5. 每替换一个 Router 块后运行 `pytest tests/ -q --tb=no`，确认无回归。

**已知问题**：
- admin.py 路由最多（36 条），可能超过 400 行限制。必要时将 manufacturing 部分再拆为 `routers/manufacturing.py`
- `shared.py` 与 `server.py` 第 6-812 行有大量代码重复，集成后应删除 server.py 中的重复部分
- auth.py 中的 `register/login/refresh` 函数需要 `request: Request` 参数（slowapi limiter 要求），已处理

### B. Phase 5：标准化收尾

| # | 任务 | 执行方法 |
|---|------|---------|
| 5.1 | 补充公开函数 docstring | 扫描 `raganything/` 下所有 `.py` 文件，对无 docstring 的公开函数添加 Google 风格文档 |
| 5.2 | 统一命名规范 | 检查 snake_case/PascalCase/UPPER_SNAKE 合规 |
| 5.3 | 统一异常处理 | 将 server.py 中 `raise HTTPException(...)` 替换为业务异常 → Router 层统一映射 |
| 5.4 | 拆分超大函数 | 扫描 >120 行的函数，提取为小函数。重点关注：server.py 中的 `query_rag`(275行)、`agent_query_stream`(390行)、`_process_uploaded_file`(121行) |
| 5.5 | 清理 TODO/FIXME | `grep -r "TODO\|FIXME\|HACK" raganything/ server.py --include="*.py"` |
| 5.6 | print() → loguru | 搜索 `print(` 调用，替换为 `logger.info/debug/warning` |
| 5.7 | pytest + ruff 零问题 | 目标：ruff check 0 errors |

### C. Phase 6：回归验证

| # | 任务 |
|---|------|
| 6.1 | 运行全量 pytest |
| 6.2 | 启动 `python server.py`，手动测试核心 API |
| 6.3 | 前端页面功能验证 |
| 6.4 | `ruff check . --exclude .venv` |
| 6.5 | 文件行数检查：server.py <300, 每个 Router <400, 子模块 <500 |
| 6.6 | 提交 PR |

---

## 3. 关键文件路径

```
c:\Users\98014\RAG-Anything\
├── server.py                          ← 主入口，待精简
├── auth.py                            ← 已清理
├── agent_manager.py                   ← 未修改
├── process_worker.py                  ← 未修改（独立子进程）
├── raganything/
│   ├── parser/                        ← ✅ 已拆分
│   ├── processor/                     ← ✅ 已拆分
│   ├── query/                         ← ✅ 已拆分
│   ├── routers/                       ← 🟡 模块就绪，待集成
│   │   ├── shared.py                  ← 742 行，与 server.py 重复
│   │   ├── auth.py                    ← 200 行
│   │   ├── knowledge.py              ← 900 行
│   │   ├── agent.py                   ← 600 行
│   │   ├── query.py                   ← 590 行
│   │   └── admin.py                   ← 860 行
│   ├── exceptions.py                  ← ✅ 已创建
│   ├── dependencies.py               ← ✅ 已创建
│   ├── utils.py                       ← ✅ 已追加工具函数
│   ├── config.py                      ← 已清理
│   ├── *.py.bak                       ← 旧文件备份
│   └── manufacturing/                 ← 未修改
├── tests/                             ← 5 个测试文件已更新路径引用
└── openspec/changes/backend-codebase-refactoring/
    ├── proposal.md                    ← 提案
    ├── design.md                      ← 设计文档
    ├── tasks.md                       ← 任务清单（含进度）
    ├── specs/                         ← 规范文件
    └── HANDOFF.md                     ← 本文档
```

---

## 4. 给接手 AI 的提示词模板

```
你正在对 RAG-Anything 项目执行后端重构的收尾工作。分支: refactor/backend-cleanup

## 当前状态
- raganything/parser、processor、query 已从单体文件拆分为子包 ✅
- raganything/routers/ 下 5 个 Router 模块已创建并可导入 ✅
- 测试: 356 passed, 2 预存失败 ✅
- server.py 仍包含 60+ 条旧的 @app. 路由，需要替换为 app.include_router()

## 首要任务：server.py Router 集成
请阅读 server.py 和 raganything/routers/ 下的所有文件，然后将 server.py 中的旧路由替换为 Router 注册。

执行方法：
1. 在 server.py 第 210 行后添加 5 个 Router 的 import 和 app.include_router() 调用
2. 删除 server.py 中对应的旧 @app. 路由处理函数（行号见本文件第2.A节）
3. 保留中间件、全局状态、辅助函数在 server.py 中
4. 每次删除一组路由后运行 pytest 确认无回归
5. 最终 server.py 目标 <300 行

## 约束
- 绝对不改动任何业务逻辑
- 所有 API 路径、请求/响应格式保持不变
- 不要删除 raganything/*.py.bak 备份文件
```

---

## 5. 已知陷阱

1. **slowapi rate limiter 需要 `request: Request` 参数** — auth.py 中 register/login/refresh 已添加。其他 Router 中使用 `@limiter.limit()` 的函数需同样处理

2. **shared.py 与 server.py 状态同步** — shared.py 从 server.py 第 6-812 行提取。如果 server.py 中的原始代码被修改，shared.py 需要同步更新。集成完成后应删除 server.py 中的重复代码，以 shared.py 为唯一数据源

3. **`global` 声明** — Router 中使用 `shared.` 前缀访问可变状态（如 `shared.kb_instances[name] = ...`），而非 `global` 声明

4. **admin.py 行数超标** — 860 行 > 400 行限制。如果需要严格合规，可将 manufacturing 路由提取到 `routers/manufacturing.py`

5. **测试路径引用** — 5 个测试文件已更新（parser/processor/query 路径变更），不要再改回去
