## Why

每次后端重启后，JWT 签名密钥被重新随机生成，导致所有已签发的 Token 全部失效，用户必须重新登录。根本原因是 `auth.py` 中 `SECRET_KEY` 和 `REFRESH_SECRET_KEY` 在未配置环境变量时使用 `secrets.token_hex(32)` 动态生成，重启即丢失。

## What Changes

- **JWT 密钥持久化**：首次启动时生成 `SECRET_KEY` 和 `REFRESH_SECRET_KEY` 并存入 `auth.db` SQLite 数据库；后续启动从数据库加载，不再随机生成
- **环境变量优先级**：如果用户在 `.env` 中显式设置了 `JWT_SECRET` / `JWT_REFRESH_SECRET`，仍优先使用环境变量（保持向后兼容）
- **数据库 schema 变更**：在 `auth.db` 中新增 `settings` 表，以 key-value 结构存储密钥等持久化配置
- **env.example 文档更新**：补充 `JWT_SECRET` 和 `JWT_REFRESH_SECRET` 的说明，让用户了解手动配置的方式

## Capabilities

### New Capabilities
- `jwt-secret-persistence`: JWT 签名密钥在 SQLite 数据库中的持久化存储与加载，确保后端重启后已签发的 Token 仍然有效

### Modified Capabilities
<!-- None - this is a new capability, no existing spec requirements are changing -->

## Impact

- `auth.py`：密钥生成逻辑改造，增加 DB 读写
- `server.py`：启动流程可能需调整 `init_db()` 调用时序
- `.env.example`：补充 `JWT_SECRET` / `JWT_REFRESH_SECRET` 文档
