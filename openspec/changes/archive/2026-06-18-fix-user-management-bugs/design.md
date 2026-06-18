## Context

用户管理模块处于从二元 `is_admin` 模型到 RBAC 角色模型的迁移中期。认证、授权、审计三个子系统各自存在独立缺陷，且缺陷组合后形成完整的攻击链。所有修复均在 `refactor/backend-cleanup` 分支上进行，数据库为 SQLite（`auth.db`），后端框架为 FastAPI + aiosqlite。

## Goals / Non-Goals

**Goals:**
- 修复暴力破解防护，使 Brute-force lockout 机制能正常计数和锁定
- 消除默认管理员弱密码，强制首次登录修改密码
- 确保 `init_db()` 创建所有必需表（`roles`, `audit_logs`），全新安装可用
- 修复审计日志在写入失败时静默丢失数据的问题
- 修复登出端点使其能撤销 Refresh Token Family
- 将 Token 黑名单持久化到 SQLite，解决重启丢失和多 Worker 不一致
- 修复 `update_user()` 静默丢弃 `role_id` 更新的问题
- 消除 `is_admin` 布尔短路，统一通过 RBAC 权限系统授权

**Non-Goals:**
- 不引入 Redis 等外部依赖（黑名单持久化使用现有 SQLite）
- 不在此变更中完整实现 MFA/2FA
- 不重构整个 RBAC 模型（保留现有 `roles` 表结构）
- 不修改前端（除登出时发送 refresh_token 外）

## Decisions

### 决策 1: Brute-force 函数统一使用 `user_id: int`

**选择**: 将 `record_failed_login()`, `reset_failed_logins()`, `check_account_locked()` 的参数改为 `user_id: int`，SQL 查询改为 `WHERE id = ?`。

**备选方案**: 保持 `username: str` 签名，修改所有调用点传字符串。

**理由**: `user_id` 是主键且不可变，避免用户名大小写、重命名等边界问题。SQL 查询走主键索引更快。

### 决策 2: Token 黑名单持久化方案

**选择**: 在 `auth.db` 中新增 `token_revocations` 表，`TokenBlacklist` 双写（内存 + DB），启动时从 DB 加载未过期条目。

**备选方案**: Redis 独立存储。被拒绝——不想引入新依赖。内存缓存 + SQLite 持久化对于单节点部署足够；水平扩展时可迁到 Redis。

### 决策 3: 默认管理员密码

**选择**: 如果 `DEFAULT_ADMIN_PASSWORD` 环境变量未设置且无已存在管理员，生成 `secrets.token_urlsafe(16)` 随机密码，打印到 stderr，并在用户记录中设置 `must_change_password=1`。

**理由**: 启动时打印随机密码是 DevOps 标准做法（如 PostgreSQL、MongoDB Atlas）。不设置环境变量也不崩溃——适合开发和低风险部署。

### 决策 4: JWT 有效期缩短

**选择**: 默认 `JWT_EXPIRY_HOURS` 从 24 改为 1。可通过环境变量配置。

**理由**: 减少 Token 被盗后的有效窗口。配合 Refresh Token 轮转机制降低风险。

## Risks / Trade-offs

- **[Risk] Token 黑名单持久化增加 SQLite I/O** → 缓存在内存，启动时批量加载，写入异步（复用现有线程模型）
- **[Risk] `role_id` 加入 `allowed_fields` 可能被误用** → `update_user()` 现已包含安全字段拒绝日志
- **[Risk] JWT TTL 缩短可能增加 Refresh Token 使用频率** → 当前架构已有 Refresh Token 轮转，权衡安全性和用户体验
- **[Risk] `is_admin` 短路移除可能导致某些合法管理员操作被拒** → Admin 角色的 `permissions` 已包含所有 13 个权限，RBAC 检查会正常通过

## Migration Plan

1. 部署前：执行 `ALTER TABLE` 添加 `token_revocations` 表（通过 `init_db()` 的 `IF NOT EXISTS`）
2. 向后兼容：`must_change_password` 对已存在的管理员账户不强制，仅对新创建的默认管理员生效
3. 回滚：恢复旧代码后功能可降级（新表不影响旧代码），但 Token 黑名单持久化功能丢失
4. 前端协调：登出时需在请求体中发送 refresh_token（前端 `AuthContext.jsx` 同步修改）
