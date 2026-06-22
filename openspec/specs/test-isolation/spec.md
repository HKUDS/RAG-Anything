# Test Isolation

## Purpose

Ensure test suites can run with isolated database instances, preventing cross-test contamination through module-level cached state. Covers dynamic database path resolution for the authentication module and token blacklist service.

## Requirements

### Requirement: DB_PATH is dynamically resolvable
认证模块 SHALL 通过函数调用动态获取数据库路径，而非使用模块导入时固定的常量，使得测试可通过环境变量切换数据库。

#### Scenario: Test fixture switches database path
- **WHEN** 测试设置 `AUTH_DB_PATH` 环境变量为新临时文件路径
- **THEN** `get_db_path()` 返回该临时文件路径
- **AND** `init_db()` 在该临时文件中创建表

#### Scenario: Multiple tests use independent databases
- **WHEN** 两个测试先后运行，各自通过 `temp_db` fixture 创建独立临时数据库
- **THEN** 每个测试的数据库操作访问各自的临时文件
- **AND** 测试之间无表冲突或数据泄漏

#### Scenario: Production fallback when env var unset
- **WHEN** `AUTH_DB_PATH` 环境变量未设置
- **THEN** `get_db_path()` 返回默认值 `./auth.db`

### Requirement: Security tests pass with proper isolation
`tests/security/test_auth.py` 中的所有测试 SHALL 在独立数据库中运行并通过。

#### Scenario: Account lock threshold test passes
- **WHEN** 对用户连续记录 4 次失败登录
- **THEN** `check_account_locked` 返回 `None`（未锁定）
- **WHEN** 记录第 5 次失败登录
- **THEN** `check_account_locked` 返回锁定消息

#### Scenario: Failed login reset test passes
- **WHEN** 在独立临时数据库中创建用户并手动设置失败计数
- **THEN** `aiosqlite.connect` 连接的数据库与 `init_db()` 使用的数据库相同
- **AND** `reset_failed_logins` 成功将计数器归零

#### Scenario: Token revocation persists in correct database
- **WHEN** `set_blacklist_db_path` 设置为临时数据库路径
- **THEN** `TokenBlacklist._persist_revoke` 写入的 `token_revocations` 表存在于该临时数据库中
- **AND** 新 `TokenBlacklist` 实例可从该数据库恢复撤销状态

#### Scenario: RBAC role change test uses correct database
- **WHEN** 测试通过 `aiosqlite.connect(temp_db)` 直接查询角色表
- **THEN** 查询的数据库与 `init_db()` 和 `create_user()` 使用的数据库相同
- **AND** `roles` 表存在且包含默认角色数据
