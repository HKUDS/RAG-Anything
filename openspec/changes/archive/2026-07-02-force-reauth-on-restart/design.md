## Context

当前架构（`persist-jwt-secrets` 变更后）：JWT 签名密钥持久化在 `auth.db` 的 `settings` 表中，重启后密钥不变，Token 保持有效。需要在此基础上增加"重启即失效"的安全策略。

## Goals / Non-Goals

**Goals:**
- 服务器每次启动生成新的 `server_start_id`，嵌入所有 JWT Token
- Token 验证时检查 `server_start_id` 匹配，不匹配则拒绝
- 保持签名密钥持久化（`.env` 或 `auth.db`）

**Non-Goals:**
- 不改变 Token 过期时间策略
- 不实现 Token 黑名单或主动吊销
- 不修改前端代码

## Decisions

### 决策 1：`server_start_id` 方案 vs. 撤销密钥持久化

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| A. 撤销密钥持久化，恢复随机密钥 | 简单 | 密钥变化导致无法区分"重启失效"和"密钥变更"；审计困难 | ❌ |
| B. 保持密钥持久化 + `server_start_id` | 语义清晰（重启失效≠密钥泄露）；密钥稳定便于审计 | 多一个 JWT claim | ✅ |

**选择 B**：两层分离——签名密钥层（持久化，保证签名一致性）和会话生命周期层（`server_start_id`，每次重启变更）。

### 决策 2：`server_start_id` 存储位置

**选择**：仅存于进程内存（`auth.py` 模块级变量），不持久化。重启自然丢失，无需清理逻辑。

### 决策 3：JWT claim 命名

使用 `sid`（server instance id）作为 JWT payload 中的 claim 名，简洁且不与标准 claim 冲突。

### 决策 4：验证失败行为

`server_start_id` 不匹配时，`decode_token()` 返回 `None`——与过期、签名无效行为一致。前端已有 401 处理逻辑，会自动跳转登录页。

## Risks / Trade-offs

- **[低风险] 多进程部署**：如果使用 `gunicorn` 多 worker，每个 worker 有自己的 `server_start_id`→ 需要确保 `server_start_id` 在主进程生成并传递给 workers。当前项目未使用多 worker，暂不处理。
- **[安全] 重启即全员登出**：运维重启会导致所有用户同时登出 → 符合设计预期

## Migration Plan

1. 部署新代码 → 首次启动生成新 `server_start_id`
2. 所有旧 Token（不含 `sid` claim，或 `sid` 不匹配）被拒绝
3. 用户重新登录获得含新 `sid` 的 Token
4. 回滚：部署旧代码 → `sid` 验证逻辑消失 → 旧 Token 恢复有效（如果密钥一致）
