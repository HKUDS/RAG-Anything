## Why

9 个已有测试失败（3 类根因）阻塞 CI 流水线，其中 7 个安全测试失败使得认证模块回归不可信，2 个集成测试失败掩盖真实的代码回归。这些失败在 `git stash` 后原代码同样存在，确认为已有问题，需独立修复。

## What Changes

- **修复 `tests/security/test_auth.py` 的 7 个测试隔离缺陷**：`DB_PATH` 模块级缓存导致 fixture 创建的临时数据库被忽略；同时修复 1 个测试逻辑错误（锁定阈值断言）
- **修复 `tests/test_callbacks.py::test_process_document_emits_callbacks`**：Mock 策略错误，`FakeLightRAG` 缺少 `ainsert` 方法
- **修复 `tests/testparser_wiring.py::test_processor_parse_document_uses_selected_parser`**：无效 PDF 文件导致 PDFium 解析失败

## Capabilities

### New Capabilities
- `test-isolation`: 认证模块支持在测试中切换数据库路径（`DB_PATH` 从模块级常量改为可重载），使 `temp_db` fixture 隔离生效
- `test-integration-fixes`: 修复回调集成测试的 Mock 策略和解析器接线测试的 PDF 文件生成

### Modified Capabilities
<!-- 不修改任何已有 spec 级行为 -->

## Impact

| 影响范围 | 文件 | 说明 |
|---------|------|------|
| 认证服务 | `raganything/services/auth.py` | `DB_PATH` 从模块级常量改为延迟解析 |
| Token 黑名单 | `raganything/services/token_blacklist.py` | `_DB_PATH` 同步支持动态切换 |
| 安全测试 | `tests/security/test_auth.py` | 修正锁定阈值断言，消除直接 `aiosqlite.connect(temp_db)` |
| 回调测试 | `tests/test_callbacks.py` | 修复 `FakeLightRAG` Mock |
| 解析器测试 | `tests/testparser_wiring.py` | 生成有效 PDF 或 Mock PDFium |
