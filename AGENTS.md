# RAG-Anything Project Instructions

## 项目核心总结（强制）

`PROJECT_SUMMARY.md` 是所有项目任务的首要阅读入口。

- 启动任何任务前，必须完整阅读 `PROJECT_SUMMARY.md`，再只对任务相关源码、配置、迁移和规格做定向核验。
- 总结用于快速建立上下文，不替代代码、数据库迁移、运行配置或 OpenSpec 主规格；发现冲突时以实际实现和验证结果为准。
- 单个任务完成前，必须由唯一协调者更新总结中的当前事实并追加近期任务记录；无持久行为变化也要记录结论。
- 并行子任务不得直接争抢总结文件，只在 handoff 提交“总结增量”，由协调者串行合并。
- 禁止在总结中写入密钥、密码、令牌、用户数据、运行日志或生成产物。

## 铁律集成

本项目遵循全局铁律（`~/.Codex/AGENTS.md`）：每次收到用户请求必须执行两级智能体调度。

### OpenSpec + 调度联动规则

使用 OpenSpec 命令时必须遵循以下时序：

```
/opsx:propose → 先调度（至少 2 专家评审提案质量）
/opsx:apply   → 先调度（至少 3 专家：执行+审查+测试）
/opsx:archive → 调度确认后归档
```

**不可跳过**：即使任务看起来简单（如单行修复、配置修改），也必须走完两级调度。OpenSpec 管产出结构化，调度管执行质量，两者叠加而非替代。

OpenSpec 还必须同步项目总结：`propose` 将总结更新列入最终任务，`apply` 在实现验证后更新，`archive` 前确认已经同步。

## 用户管理系统 (RBAC v2)

本项目使用基于角色的访问控制（RBAC），替代旧的 `is_admin` 二值模型。

### 角色
- **super_admin** — 超级管理员，拥有全部权限
- **dept_admin** — 系部管理员，管理用户、知识库、智能体和业务能力
- **teacher** — 主讲教师，可管理自有知识库和智能体
- **assistant** — 助理教师，可维护知识库内容并使用智能体
- **student** — 学生，只使用获授权的读取和问答能力

### 权限模型
详见 `raganything/permissions.py` 中的 `Permission` 类。权限格式：`resource:action`（如 `users:read`, `kb:write`）。

### 数据库
- 用户、角色、审计和 Token 撤销数据：PostgreSQL（当前认证服务无 SQLite 回退）
- 迁移：`migrations/001_pg_schema.sql`、`migrations/015_restore_5level_rbac.sql`
- `is_admin` 仅为兼容字段，由 `super_admin` 角色派生

### 关键文件
| 文件 | 说明 |
|------|------|
| `PROJECT_SUMMARY.md` | 项目核心总结、当前状态和任务复盘 |
| `raganything/permissions.py` | 权限常量和默认角色 |
| `raganything/services/auth.py` | 认证服务 + 角色/权限查询 |
| `raganything/services/pg_auth_repo.py` | PostgreSQL 用户/角色、Token 撤销和审计仓库 |
| `raganything/dependencies.py` | `require_permission()` FastAPI 依赖 |
| `raganything/routers/auth.py` | 认证 + 管理员用户/角色/审计端点 |
