## 1. 认证模块：DB_PATH 动态解析（test-isolation 核心）

- [x] 1.1 在 `raganything/services/auth.py` 中添加 `get_db_path()` 函数，每次调用读取 `os.getenv("AUTH_DB_PATH", "./auth.db")`
- [x] 1.2 将 `raganything/services/auth.py` 中所有 `str(DB_PATH)` 替换为 `str(get_db_path())`（约 15 处：`init_db`, `create_user`, `get_user_by_username`, `get_user_by_id`, `check_account_locked`, `record_failed_login`, `reset_failed_logins` 等）
- [x] 1.3 将 `raganything/services/token_blacklist.py` 中 `_DB_PATH` 改为读取 `AUTH_DB_PATH` 环境变量，与 auth 模块保持一致

## 2. 安全测试修复：测试隔离与断言修正

- [x] 2.1 修正 `test_account_locks_after_max_failures`：将 "5次后不锁定→6次后锁定" 改为 "4次后不锁定→5次后锁定"
- [x] 2.2 移除所有测试中直接 `aiosqlite.connect(temp_db)` 的代码，改用 auth 模块的函数（`check_account_locked`, `reset_failed_logins` 等），确保使用 `get_db_path()` 返回的同一数据库
- [x] 2.3 修正 `test_token_revocation_persists_to_db`：确保 `set_blacklist_db_path` 和 `init_db()` 使用同一数据库文件
- [x] 2.4 运行 `tests/security/test_auth.py` 全部 12 个测试确认通过

## 3. 回调测试修复：FakeLightRAG Mock 补全

- [x] 3.1 为 `test_process_document_emits_callbacks` 中的 `FakeLightRAG` 类添加 `ainsert` async 方法（空实现：`async def ainsert(self, **kwargs): pass`）
- [x] 3.2 运行 `tests/test_callbacks.py` 全部 15 个测试确认通过

## 4. 解析器接线测试修复：修复 monkeypatch 目标

- [x] 4.1 修正 monkeypatch 目标：`doc_processor.py` 使用 `from raganything.parser import get_parser` 导入，需 patch `doc_processor.get_parser` 而非 `raganything.parser.get_parser`
- [x] 4.2 运行 `tests/testparser_wiring.py` 全部 3 个测试确认通过

## 5. 验证

- [x] 5.1 运行全量测试套件 `python -m pytest tests/ -v --tb=short` — **406 passed, 3 skipped, 0 failed**
- [x] 5.2 确认 `tests/security/test_auth.py` (12/12)、`tests/test_callbacks.py` (15/15)、`tests/testparser_wiring.py` (3/3) 全部通过
