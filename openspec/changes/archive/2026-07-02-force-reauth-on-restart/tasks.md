## 1. 新增 server_start_id (auth.py)

- [x] 1.1 在模块顶部新增 `SERVER_START_ID` 变量，使用 `uuid.uuid4().hex` 在导入时生成
- [x] 1.2 修改 `create_token()`：在 JWT payload 中增加 `sid` claim，值为 `SERVER_START_ID`
- [x] 1.3 修改 `create_refresh_token()`：在 JWT payload 中增加 `sid` claim，值为 `SERVER_START_ID`

## 2. 增强 Token 验证 (auth.py)

- [x] 2.1 修改 `decode_token()`：解码后校验 `payload.get("sid") == SERVER_START_ID`，不匹配返回 `None`
- [x] 2.2 修改 `decode_refresh_token()`：解码后校验 `payload.get("sid") == SERVER_START_ID`，不匹配返回 `None`

## 3. 验证

- [x] 3.1 启动服务器 → 登录获取 Token → 调用 `/api/auth/me` 确认有效
- [x] 3.2 重启服务器 → 使用旧 Token 调用 `/api/auth/me` → 确认返回 401
- [x] 3.3 重启后重新登录 → 新 Token 调用 `/api/auth/me` → 确认有效
- [x] 3.4 使用 Refresh Token 刷新 → 确认新 Token 含当前 `sid`
