## Context

RAG-Anything 后端经多轮功能迭代，核心模块严重膨胀：`server.py`(3752 行) 承载全部路由和应用启动逻辑；`parser.py`(3346 行)、`processor.py`(2786 行)、`query.py`(1818 行) 单体文件职责混杂。代码中存在未使用导入、废弃函数/变量、冗余重复逻辑（如多处重复实现相同的 JSON 响应构造、错误处理模式）、失效注释、遗留测试代码等问题。

**约束**：
- 不得改动任何业务逻辑、API 契约、数据库操作
- 所有现有 API 端点路径、请求/响应格式 100% 不变
- `pytest` 测试全部通过
- 不影响生产环境运行

## Goals / Non-Goals

**Goals:**
- 将 `server.py` 拆分为 5 个 Router 模块 + 启动骨架，文件 < 300 行
- 拆分 `parser.py`、`processor.py`、`query.py` 等超长文件为子包
- 清除所有无效冗余代码（未使用导入、废弃函数、闲置变量、重复逻辑、失效注释、临时测试代码）
- 提取通用模式（错误响应、分页、依赖注入）为公共工具
- 统一命名规范（函数/变量/类）、异常处理方式、注释格式
- 每个函数保持可被 AI 单次上下文完整理解的复杂度（建议 < 80 行）
- 减少代码嵌套层级（目标：最大嵌套深度 ≤ 3）

**Non-Goals:**
- 不修改任何业务逻辑、判断条件、业务分支
- 不修改数据库表结构或查询语句
- 不修改 API 端点路径、参数、响应 schema
- 不引入新的第三方依赖
- 不修改前端代码
- 不引入新的功能特性
- 不进行性能优化（除非冗余代码的消除自然带来提升）

## Decisions

### 1. Router 拆分策略：按 API 前缀分组

**决策**: 将 `server.py` 中的路由按 API 前缀拆分为 5 个 Router 文件：
- `raganything/routers/auth.py` — `/api/auth/*`, `/api/admin/users/*`
- `raganything/routers/knowledge.py` — `/api/upload/*`, `/api/knowledge/*`, `/api/kb/*`, `/api/files/*`
- `raganything/routers/agent.py` — `/api/agents/*`
- `raganything/routers/query.py` — `/api/query/*`, `/api/conversations/*`
- `raganything/routers/admin.py` — `/api/settings`, `/api/monitor/*`, `/api/health`, `/api/workflows/*`, `/api/manufacturing/*`

**替代方案及权衡**:
| 方案 | 优点 | 缺点 | 选择理由 |
|------|------|------|---------|
| 按前缀分组 | 自然对齐 API 文档；同级文件少(5个) | 部分 router 仍偏大 | ✅ 最自然的分组，文件数可控 |
| 按功能领域（DDD Bounded Context） | 语义更清晰 | 需 10+ 文件，过度碎片化 | 当前项目规模不适合 DDD 式拆分 |
| 保持单体 server.py | 无 | 3752 行，AI 难以分析 | ❌ 正是要解决的问题 |

### 2. 超长模块拆分策略：子包模式

**决策**: 对 `parser.py`(3346 行)、`processor.py`(2786 行)、`query.py`(1818 行) 采用子包模式拆分：

```
raganything/
├── parser/                  # 原 parser.py (3346 行)
│   ├── __init__.py          # 导出公共接口
│   ├── pdf_parser.py        # PDF 解析相关
│   ├── office_parser.py     # Office 文档解析
│   ├── image_parser.py      # 图片解析
│   ├── url_parser.py        # URL 内容抓取
│   └── base.py              # 解析器基类和接口
├── processor/               # 原 processor.py (2786 行)
│   ├── __init__.py
│   ├── doc_processor.py     # 文档处理
│   ├── chunk_processor.py   # 分段处理
│   ├── embed_processor.py   # 向量化处理
│   └── batch_processor.py   # 批处理
├── query/                   # 原 query.py (1818 行)
│   ├── __init__.py
│   ├── conversation.py      # 对话管理
│   ├── query_pipeline.py    # 查询管线
│   ├── stream.py            # 流式响应
│   └── citation.py          # 引用处理
```

**关键原则**: 每个子模块 ≤ 500 行；`__init__.py` 仅做 re-export，保持对外接口完全兼容。

### 3. 通用模式提取策略

**决策**: 提取以下重复模式为公共工具：

| 重复模式 | 提取位置 | 说明 |
|---------|---------|------|
| 错误响应 JSON 构造 | `raganything/utils.py` → `error_response(message, code, status)` | 多处 `raise HTTPException(...)` 前构造 JSON |
| 分页参数解析 | `raganything/dependencies.py` → `PaginationParams` | 多处 `page = int(request.query_params.get(...))` |
| 知识库访问验证 | `raganything/dependencies.py` → `verify_kb_access(kb_name, user)` | 多处重复的 kb 权限检查 |
| 异步后台任务包装 | `raganything/utils.py` → `run_background_task(coro)` | 统一的 background_tasks 处理 |
| SSE 流式响应构建 | `raganything/utils.py` → `sse_event(data, event_type)` | 多处重复的 SSE 格式化 |

### 4. 命名与注释规范

**决策**: 统一采用以下命名约定：

| 类别 | 规范 | 示例 |
|------|------|------|
| 函数 | snake_case，动词开头 | `get_user_knowledge_bases()` |
| 类 | PascalCase | `ConversationManager` |
| 变量 | snake_case，名词 | `user_id`, `kb_list` |
| 常量 | UPPER_SNAKE | `DEFAULT_MAX_TOKENS` |
| 私有函数/变量 | `_` 前缀 | `_parse_internal_id()` |
| 异步函数 | 保持现有 async 声明 | `async def fetch_document()` |

**注释规范**:
- 每个公开函数/类必须有 docstring（Google style），包含 `Args:` / `Returns:` / `Raises:`
- 关键业务逻辑上方添加单行注释说明意图
- 删除所有无意义的"注释掉的老代码"和 `# TODO: delete this` 类临时标记

### 5. 异常处理统一策略

**决策**: 统一异常处理模式：
- 业务异常：定义 `raganything/exceptions.py` 统一业务异常类层次
- API 层：Router 级别统一 `try/except` → HTTPException 映射
- 日志：使用 loguru 统一记录，包含请求上下文（user_id, trace_id）

**替代方案**: Flask-style error handlers（`@app.exception_handler`）—— 不采用，因为 Router 级别处理更显式、更易调试。

### 6. 重构执行顺序

**决策**: 采用"自底向上"顺序，确保每步验证通过后再进行下一步：

```
Phase 1: 冗余清理（最低风险）
  → 删除未使用导入、废弃函数、闲置变量、失效注释
Phase 2: 通用模式提取
  → 提取重复逻辑到 utils.py / dependencies.py / exceptions.py
Phase 3: 核心模块拆分
  → parser.py / processor.py / query.py 子包化
Phase 4: Router 拆分
  → server.py → 5 routers + 启动骨架
Phase 5: 标准化收尾
  → 统一命名、注释、异常处理
Phase 6: 回归验证
  → 全量 pytest + 手动烟雾测试
```

**理由**: 每步独立可验证；出现问题可精确定位到单步；冗余清理先行可减少后续步骤的代码搬运量。

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 重构过程中引入逻辑错误 | 业务功能异常 | 每 Phase 完成后运行全量 pytest；保留原始文件备份 |
| `import` 路径变更导致运行时 ImportError | 服务启动失败 | 确保 `__init__.py` 中保留原模块的完整 re-export；PyCharm/VSCode 全局搜索验证 |
| Router 拆分后中间件/依赖注入失效 | API 行为差异 | 将 `limiter`、`get_current_user` 等提取到 `dependencies.py` 统一注入 |
| 循环导入问题 | 启动失败 | 遵循 `utils → core → routers` 的单向依赖原则；延迟导入必要时使用 |
| 文件改名导致 git blame 断裂 | 代码历史追溯困难 | 使用 `git mv` 进行文件移动；PR 描述中记录路径映射表 |
| 大文件重构时合并冲突 | 阻塞其他 PR | 此为独立 PR，建议锁定相关文件在重构期间的修改 |

## Migration Plan

1. 从 `feature/custom-enhancements` 创建 `refactor/backend-cleanup` 分支
2. 按 Phase 1→6 顺序执行，每 Phase 提交一个 commit
3. Phase 6 完成后提交 PR，运行 CI 全量测试
4. 代码审查通过后合并到 `feature/custom-enhancements`
5. **回滚策略**: 每个 Phase 独立 commit，可直接 `git revert` 特定 Phase

## Open Questions

1. `raganything/manufacturing/` 子包结构已较合理，是否需要纳入本次重构范围？ → 建议仅做冗余清理（Phase 1），不做结构拆分
2. 测试文件清理：当前有 29 个测试文件，部分可能已失效。清理策略？ → Phase 0：先运行全量 pytest，标记失败测试，与用户确认后移除或修复
