## Why

用户管理模块存在多个互相叠加的安全缺陷和功能 Bug，包括暴力破解防护完全失效、默认管理员弱密码、RBAC 表初始化缺失、审计日志静默失败、登出无法撤销 Refresh Token、Token 黑名单因重启丢失、角色更新静默丢弃等。这些 Bug 组合形成一个完整攻击链——攻击者可从零到完全系统攻陷且不留审计痕迹。必须在生产部署前修复。

## What Changes

- 修复暴力破解防护：将 `record_failed_login`、`reset_failed_logins`、`check_account_locked` 的参数从 `username: str` 改为 `user_id: int`，SQL 查询改为 `WHERE id = ?`，消除 SQLite 类型混淆导致的静默失效
- 移除硬编码默认管理员密码 `admin123`，首次部署时生成随机密码并在首次登录时强制修改
- 将 `roles`、`audit_logs` 表的创建移入 `init_db()`，确保全新安装可用
- 修复审计日志写入失败被静默吞没：在写入成功后再清空队列，失败时记录错误并重试
- 修复登出端点：接受请求体中的 refresh_token，提取 `rfam` 并撤销 Refresh Token Family
- 将 Token 黑名单持久化到 SQLite `token_revocations` 表，解决重启丢失和多 Worker 不共享问题
- 在 `update_user()` 的 `allowed_fields` 中加入 `role_id`，修复角色更新被静默丢弃
- 移除 `require_permission()` 中 `is_admin` 布尔短路，改为统一通过 RBAC 角色权限系统检查
- 修复 `get_current_user()` 中 `is_admin` 回退到废弃 `is_admin` 列的逻辑
- 减少 JWT Access Token 默认有效期从 24h 到 1h

## Capabilities

### New Capabilities

- `brute-force-protection`: 账户锁定机制——N 次失败后锁定，锁定期间拒绝登录和已有 Token 请求
- `secure-default-admin`: 首次部署安全管理员引导流程——随机密码 + 首次登录强制修改
- `token-revocation`: Token 撤销持久化——登出撤销 Refresh Token Family，重启后撤销状态保持
- `audit-log-integrity`: 审计日志完整性——写入失败时告警并重试，不静默丢失数据

### Modified Capabilities

- `rbac-authorization`: 移除 `is_admin` 布尔短路，统一通过角色权限系统检查；移除 `get_current_user()` 中废弃列的 fallback

## Impact

- **Affected code**: `raganything/services/auth.py`（暴力破解函数签名、init_db、密码默认值、JWT TTL）、`raganything/services/audit.py`（_flush 错误处理）、`raganything/services/token_blacklist.py`（持久化改造）、`raganything/dependencies.py`（is_admin 双路径移除）、`raganything/routers/auth.py`（登出、暴力破解调用点修正）
- **Breaking**: `record_failed_login(username: str)` → `record_failed_login(user_id: int)`，所有调用点需更新
- **Database schema**: 新增 `token_revocations` 表，`init_db()` 新增 `roles`、`audit_logs` 表创建
- **Frontend**: 登出时需在请求体中发送 refresh_token
