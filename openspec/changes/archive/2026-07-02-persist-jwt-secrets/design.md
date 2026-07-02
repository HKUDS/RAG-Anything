## Context

RAG-Anything 使用 JWT (HS256) 进行无状态认证。`auth.py` 中的 `SECRET_KEY` 和 `REFRESH_SECRET_KEY` 在未配置环境变量时，通过 `secrets.token_hex(32)` 每次启动动态生成。用户账号数据已通过 `auth.db` SQLite 持久化，但签名密钥未持久化，导致重启后所有已签发的 Token（Access Token + Refresh Token）全部失效。

当前项目的 `env.example` 未包含 `JWT_SECRET` 和 `JWT_REFRESH_SECRET` 的说明，使得用户不知道可以通过环境变量手动固定密钥。

### 约束
- 必须保持向后兼容：已在 `.env` 中设置 `JWT_SECRET` 的用户不应受影响
- 不能破坏现有 `auth.db` 的 `users` 表结构
- 最小改动原则：在现有架构内解决问题，不引入新依赖

## Goals / Non-Goals

**Goals:**
- 确保 JWT 签名密钥在服务器重启后保持不变
- 用户登录状态在重启后持续有效（只要 Token 未过期）
- 更新 `env.example` 文档，让用户了解 JWT 密钥配置

**Non-Goals:**
- 不改变 JWT 的过期策略（24h access token, 7d refresh token 保持不变）
- 不引入外部密钥管理服务（如 HashiCorp Vault）
- 不改变 Token 的签发/验证流程
- 不修改前端代码

## Decisions

### 决策 1：密钥存储方案 — SQLite `settings` 表

**方案**：在 `auth.db` 中新建 `settings` 表（key-value 结构），首次启动生成随机密钥并写入，后续启动从表读取。

**备选方案对比**：

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| A. 在 `.env` 写入固定密钥 | 简单直接 | 修改 .env 文件有风险（覆盖用户配置）；docker 部署时不可靠 | ❌ |
| B. 生成固定密钥文件（如 `.jwt_secret`） | 简单 | 多一个文件管理；容器重启可能丢失 | ❌ |
| C. SQLite `settings` 表 | 与现有架构一致（已用 auth.db）；事务安全；Docker volume 可持久化 | 需一次 schema 迁移 | ✅ |
| D. 强制用户在 `.env` 中设置 | 零代码改动 | 对用户不友好；不改代码问题依旧存在 | ❌ |

**选择 C**：复用现有 `auth.db`，符合项目已有的 SQLite 持久化模式。

### 决策 2：优先级 — 环境变量 > 数据库

加载逻辑：
1. 检查 `JWT_SECRET` 环境变量 → 如果设置，直接使用（保持向后兼容）
2. 否则检查 `auth.db` 的 `settings` 表 → 如果存在，加载
3. 否则生成新的随机密钥，存入 `settings` 表

这确保：
- 已在 `.env` 配置密钥的用户不受影响
- 新用户/未配置用户自动获得持久化密钥
- 用户可以在 `.env` 中覆盖数据库中的密钥

### 决策 3：settings 表设计

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

极简设计，仅存储 key-value 对。当前仅存储 `jwt_secret` 和 `jwt_refresh_secret`，将来可扩展存储其他持久化配置。

## Risks / Trade-offs

- **[低风险] SQLite 并发写入**：`settings` 表仅在启动时读写一次，不存在并发竞争 → 无需额外处理
- **[低风险] 数据库文件丢失**：如果 `auth.db` 被删除，密钥会重新生成，但用户的 `users` 表也会丢失（影响等同） → 与现有风险一致
- **[安全注意] 密钥明文存储**：密钥以明文存入 SQLite，与 `.env` 文件中明文存储安全等级相同。`auth.db` 应采用文件系统权限保护（如 `chmod 600`） → 可在后续迭代中考虑加密存储

## Migration Plan

1. **部署步骤**：
   - 部署新版代码
   - 启动时 `init_db()` 自动创建 `settings` 表并生成/加载密钥
   - 现有活跃 Token 会在旧密钥失效后自然过期（用户需重新登录一次）
2. **回滚**：回滚代码到旧版本，密钥恢复为每次启动随机生成（回滚后用户需重新登录）
3. **零停机**：不涉及数据库迁移锁表问题（只是新增一张小表）

## Open Questions

- 无
