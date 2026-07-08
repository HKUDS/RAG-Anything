# RAG-Anything Project Instructions

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

## 用户管理系统 (RBAC v2)

本项目使用基于角色的访问控制（RBAC），替代旧的 `is_admin` 二值模型。

### 角色
- **admin** — 系统管理员，拥有全部权限
- **editor** — 内容编辑，可读写知识库和智能体
- **viewer** — 只读用户

### 权限模型
详见 `raganything/permissions.py` 中的 `Permission` 类。权限格式：`resource:action`（如 `users:read`, `kb:write`）。

### 数据库
- 用户/角色数据：`auth.db`（SQLite）
- 迁移脚本：`scripts/migrate_to_rbac.py`
- `is_admin` 字段保留但已弃用，由 `roles` 表派生

### 关键文件
| 文件 | 说明 |
|------|------|
| `raganything/permissions.py` | 权限常量和默认角色 |
| `raganything/services/auth.py` | 认证服务 + 角色/权限查询 |
| `raganything/services/token_blacklist.py` | Token 黑名单 |
| `raganything/services/audit.py` | 审计日志 |
| `raganything/dependencies.py` | `require_permission()` FastAPI 依赖 |
| `raganything/routers/auth.py` | 认证 + 管理员用户/角色/审计端点 |
