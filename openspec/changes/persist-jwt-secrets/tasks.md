## 1. 数据库 Schema 变更 (auth.py)

- [ ] 1.1 在 `init_db()` 中新增 `settings` 表的 CREATE TABLE IF NOT EXISTS（`key TEXT PRIMARY KEY, value TEXT NOT NULL`）

## 2. 密钥持久化逻辑 (auth.py)

- [ ] 2.1 新增 `_init_secret_keys()` 函数：按"环境变量 > 数据库 > 生成并持久化"三级优先级加载 `SECRET_KEY` 和 `REFRESH_SECRET_KEY`
- [ ] 2.2 新增 `_get_or_create_setting(key, default_generator)` 辅助函数：从 `settings` 表读取，不存在则生成并写入
- [ ] 2.3 修改模块级 `SECRET_KEY` 和 `REFRESH_SECRET_KEY` 常量为延迟初始化（在 `init_db()` 完成后赋值），避免模块导入时 DB 未就绪

## 3. 启动流程适配 (server.py)

- [ ] 3.1 确认 `init_db()` 在所有 Token 操作之前调用（当前已正确：`init_db()` 在 lifespan startup 中调用，位于路由注册之前）

## 4. 文档更新

- [ ] 4.1 更新 `env.example`：在 `### Login Configuration` 区域添加 `JWT_SECRET` 和 `JWT_REFRESH_SECRET` 的说明

## 5. 验证

- [ ] 5.1 手动验证：启动服务器 → 登录获取 Token → 重启服务器 → 使用原 Token 访问 `/api/auth/me` 确认仍然有效
- [ ] 5.2 验证环境变量优先级：在 `.env` 中设置 `JWT_SECRET=test_override` → 重启 → 确认密钥使用覆盖值
