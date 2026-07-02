## Why

服务器重启后，所有已签发的 JWT Token 必须失效，强制用户重新登录。这是一个安全策略要求：重启可能伴随配置变更、权限更新或安全补丁，应确保所有旧会话被清除。此前实现的 JWT 密钥持久化使 Token 在重启后依然有效，与安全策略相悖。

## What Changes

- **新增 `server_start_id`**：每次服务器启动时生成唯一标识（UUID4），嵌入 JWT payload
- **Token 验证增强**：`decode_token()` / `decode_refresh_token()` 校验 `server_start_id` 与当前服务器一致，不匹配则拒绝
- **保留密钥持久化**：JWT 签名密钥仍从 `auth.db` 的 `settings` 表加载（避免随机密钥导致的安全审计困难），`server_start_id` 作为独立的会话失效层
- **保留环境变量优先级**：`.env` 中的 `JWT_SECRET` 仍可覆盖数据库中的密钥
- **前端不变**：前端已有的 Token 验证和自动跳转逻辑已正确处理 Token 被拒场景

## Capabilities

### New Capabilities
- `server-session-invalidation`: 服务器启动时生成唯一标识并嵌入 JWT，重启后所有旧 Token 因标识不匹配而被拒绝

### Modified Capabilities
- `jwt-secret-persistence`: Token 在服务器重启后不再保持有效（`server_start_id` 变化导致旧 Token 失效），但签名密钥本身仍持久化

## Impact

- `auth.py`：新增 `SERVER_START_ID`，修改 `create_token()` / `create_refresh_token()` / `decode_token()` / `decode_refresh_token()`
- 不影响前端代码
