# Password Policy Enforcement

统一前后端密码复杂度策略，Token 服务端失效机制，以及密码管理增强。

## ADDED Requirements

### Requirement: Unified password complexity rules
系统 SHALL 在所有用户创建和密码修改场景中强制执行统一的密码复杂度规则：最少 8 个字符，最多 128 个字符，必须包含以下 4 类中至少 3 类：大写字母、小写字母、数字、特殊字符。此规则 MUST 在前端和后端同时校验。

#### Scenario: Strong password accepted
- **WHEN** 用户设置密码 "MyStr0ng!Pass"
- **THEN** 系统接受密码（包含大写、小写、数字、特殊字符四类）

#### Scenario: Password too short rejected
- **WHEN** 用户设置密码 "Ab1!"（仅 4 位）
- **THEN** 系统返回 422，错误消息 "Password must be at least 8 characters"

#### Scenario: Missing character classes rejected
- **WHEN** 用户设置密码 "abcdefgh"（仅小写字母）
- **THEN** 系统返回 422，错误消息指明需要 4 类中至少 3 类字符

#### Scenario: Frontend real-time validation
- **WHEN** 用户在注册表单或创建用户对话框中输入密码
- **THEN** 前端实时显示密码满足条件的进度指示器（长度 ✓、大写 ✓、小写 ✗、数字 ✓、特殊 ✗）

### Requirement: Token revocation on logout
系统 SHALL 在用户登出时将当前 Access Token 的 JTI 加入服务端黑名单。每次认证请求 MUST 校验 Token 是否已被撤销。

#### Scenario: Logged out token rejected
- **WHEN** 用户登出后使用同一 Access Token 访问受保护端点
- **THEN** 系统返回 401 Unauthorized

#### Scenario: Blacklist auto-cleanup
- **WHEN** 已撤销 Token 超过其原始过期时间
- **THEN** 系统在下次黑名单查询时自动清理该条目

### Requirement: Refresh token rotation
系统 SHALL 在刷新 Access Token 时同步轮转 Refresh Token。旧的 Refresh Token MUST 被撤销，新的 Refresh Token MUST 返回给客户端。

#### Scenario: Token refresh with rotation
- **WHEN** 客户端使用有效 Refresh Token 调用 `POST /api/auth/refresh`
- **THEN** 系统返回新的 Access Token 和新的 Refresh Token，旧的 Refresh Token 被撤销

#### Scenario: Reused refresh token detected
- **WHEN** 已被轮转撤销的 Refresh Token 再次使用
- **THEN** 系统返回 401，并撤销该用户所有 Refresh Token（防重放攻击）

### Requirement: Must-change-password enforcement
系统 SHALL 在用户首次登录（管理员创建的初始密码）时要求修改密码。`must_change_password=True` 的用户 MUST 在修改密码前无法访问除 `PUT /api/auth/change-password` 外的任何受保护端点。

#### Scenario: First login redirect to password change
- **WHEN** `must_change_password=True` 的用户访问任何受保护端点
- **THEN** 系统返回 403，错误码 `PASSWORD_CHANGE_REQUIRED`，提示用户先修改密码

#### Scenario: Password change clears flag
- **WHEN** 用户成功通过 `PUT /api/auth/me/password` 修改密码
- **THEN** 系统清除 `must_change_password` 标记并返回成功
