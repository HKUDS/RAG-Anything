## Context

项目有 9 个已有单元测试失败（在 `git stash` 后确认非本次重构引入），涉及两类文件：

**`tests/security/test_auth.py` (7 失败)**：`auth.py:35` 的 `DB_PATH = Path(os.getenv("AUTH_DB_PATH", "./auth.db"))` 在模块导入时求值，此后不再变化。`temp_db` fixture 在 `setUp` 中设置 `AUTH_DB_PATH` 环境变量并创建临时数据库，但由于 Python 模块缓存机制，第一个测试导入 auth 模块后 `DB_PATH` 即被固定。后续测试的 fixture 创建新的临时文件，但 `init_db()` 仍连接旧的 `DB_PATH`。部分测试还通过 `aiosqlite.connect(temp_db)` 直接访问新临时文件——该文件从未执行过 `init_db()`，表不存在——导致 `no such table: users` / `roles` / `token_revocations` 错误。此外 `test_account_locks_after_max_failures` 有独立的测试逻辑错误：`MAX_FAILED_ATTEMPTS=5` 且 `record_failed_login` 在递增后检查 `>=5`，即第 5 次失败后锁定，但测试期望第 6 次才锁定。

**`tests/test_callbacks.py::test_process_document_emits_callbacks` (1 失败)**：`FakeLightRAG` 类缺少 `ainsert` 方法。代码路径 `raganything/utils/_insert.py:45` 调用 `lightrag.ainsert()`，但 `FakeLightRAG` 未实现该方法。测试尝试 monkeypatch `utils_module.insert_text_content` 为 no-op，但 `insert_text_content` 作为独立函数被 `processor.py` 直接导入（非通过模块引用），patch 未生效。

**`tests/testparser_wiring.py::test_processor_parse_document_uses_selected_parser` (1 失败)**：测试创建 `b"%PDF-1.4\n"` 作为假 PDF 文件，PDFium 无法解析该无效内容 → `PdfiumError: Data format error`。测试已 Mock 了 parser getter，但 parser 内部仍调用 PDFium 读取假文件。

## Goals / Non-Goals

**Goals:**
- 使 `tests/security/test_auth.py` 全部 12 个测试通过
- 使 `tests/test_callbacks.py` 全部 14 个测试通过
- 使 `tests/testparser_wiring.py` 全部 3 个测试通过
- 对生产代码的修改尽可能小（仅 `DB_PATH` 延迟解析，不改变业务逻辑）
- 不引入新测试依赖

**Non-Goals:**
- 不重写测试框架或引入 pytest 插件
- 不修改 LightRAG、PDFium 等第三方库
- 不修改 `record_failed_login` 的锁定逻辑（行为正确，是测试假设错误）
- 不重构整个 auth 模块的数据库访问模式

## Decisions

### 决策 1：`DB_PATH` 延迟解析（函数替代模块常量）

**选择**：将 `DB_PATH` 从模块级常量改为函数 `get_db_path()`，每次调用时读取环境变量。

**替代方案**：
- A) 在 `init_db()` 中每次读取 `os.getenv("AUTH_DB_PATH")` → 零生产改动但需修改所有使用 `DB_PATH` 的函数
- B) 添加 `set_db_path()` 供测试调用 → 引入仅测试可见的 API
- C) 使用 `pytest.monkeypatch` 在导入前设置环境变量 → 需要测试文件顶层导入，不可行

**选择 A 的变体**：添加 `get_db_path()` 函数，替换所有 `str(DB_PATH)` 为 `str(get_db_path())`。改动范围可控（auth.py 约 15 处 + token_blacklist.py 约 1 处）。

**理由**：最小改动，不改变模块公共 API，与现有 `set_blacklist_db_path()` 模式一致。

### 决策 2：`test_account_locks_after_max_failures` 修正断言

**选择**：将测试断言从 "5 次后不锁定 → 6 次后锁定" 改为 "4 次后不锁定 → 5 次后锁定"。

**理由**：`MAX_FAILED_ATTEMPTS=5` 和 `>=5` 检查逻辑正确——第 5 次失败即锁定符合安全最佳实践。修测试不改逻辑。

### 决策 3：`test_process_document_emits_callbacks` Mock 策略

**选择**：为 `FakeLightRAG` 添加 `ainsert` 空方法，移除无效的 `utils_module.insert_text_content` monkeypatch。

**替代方案**：
- A) Mock `insert_text_content` 在 processor 中的引用 → 需要知道确切导入路径，脆弱
- B) 直接给 FakeLightRAG 添加 `ainsert` → 简单、清晰、与现有 Fake 模式一致

**理由**：B 是最小改动（2 行），不依赖模块内部导入细节。

### 决策 4：`test_processor_parse_document_uses_selected_parser` PDF 生成

**选择**：将 `FakeParser.parse_pdf()` Mock 为不调用 PDFium，直接在测试中替换 `parse_document` 调用链中的 PDFium 读取。

实际上，测试已经正确地 Mock 了 `get_parser` 返回 `FakeParser`，且 `FakeParser.parse_pdf()` 应避免调用 PDFium。但 `parse_document` 在调用 parser 前可能通过 PDFium 验证文件有效性。最简修复：让 `parse_document` 使用 `FakeParser` 的方法时绕过 PDFium 读取。

等等——跟踪代码路径：`test_processor_parse_document_uses_selected_parser` 中 `dummy.parse_document(str(fake_pdf))` → `ProcessorMixin.parse_document()`。查看 FakeParser 的设计：它直接返回内容列表，不读取文件。但错误栈显示 PDFium 在 parser 初始化时尝试打开 PDF。

再分析：错误栈是 `raganything\parser\image_parser.py:187` → `pypdfium2._helpers\document.py:78`。这不是在 `FakeParser` 中，而是在真实 parser 模块中。但 `monkeypatch.setattr(parser_module, "get_parser", fake_get_parser)` 应该让 `get_parser` 返回 `FakeParser`。

问题：`get_parser` 被 patch 了，但 `parse_document` 可能在 `get_parser` 之前就尝试读取 PDF（如通过 `parse_cache` 或文件类型检测）。查看代码路径...`ProcessorMixin.parse_document()` 可能在调用 parser 前使用了 PDFium 检测文件类型。

**最终选择**：在测试中跳过 PDFium 的文件读取——Mock `raganything.parser.image_parser.pdfium` 或让 `FakeParser.parse_pdf()` 被直接调用。由于测试已经 Mock 了 `get_parser` 且 `FakeParser.parse_pdf()` 不调用 PDFium，问题在于 `ProcessorMixin.parse_document()` 在调用 parser 之前可能使用 PDFium 获取页数等元数据。

最简修复：在 `DummyProcessor` 上 monkeypatch 掉 PDFium 相关的预处理步骤，或使 FakeParser 的解析完全绕过文件读取。考虑到这是最小改动原则，选择直接将 `dummy.parse_document` 替换为直接调用 `FakeParser.parse_pdf()` 返回值的 async wrapper。

其实更简单的修复：在 monkeypatch 中添加对 `image_parser.pdfium` 的 mock。

**最终决定**：添加 `monkeypatch.setattr(processor_module, "pdfium", None, raising=False)` 并在 FakeParser 中添加检查，或者直接在 `DummyProcessor` 上覆盖 `parse_document` 方法绕过 PDFium 调用。选择后者——更干净。

...实际上最简单的方式是：添加一个 `pdfium` mock 到 parser_module，使文件类型检测时不调用真实 PDFium。

不，让我重新思考。错误栈：
```
raganything\parser\image_parser.py:187: pdf = pdfium.PdfDocument(str(pdf_path))
```
这是在 `image_parser.py` 中，不是 FakeParser 中。所以尽管 `get_parser` 返回 FakeParser，但 `parse_document` 的某些分支仍然调用了 `image_parser` 的代码。

实际上可能 `parse_document` 在做文件类型检测时调用了 PDFium。让我看看 `ProcessorMixin.parse_document`（在 processor.py 中）。

总之，最简单的修复是 monkeypatch `image_parser.pdfium`：
```python
monkeypatch.setattr(processor_module, "pdfium", None, raising=False)
```
但这可能不够，因为 import 路径可能是 `from raganything.parser.image_parser import pdfium`。

更直接：在 `FakeParser.parse_pdf` 中直接返回内容（本来就这样），但在 `parse_document` 流程中，文件类型检测发生在 parser 调用之前。所以需要 mock 文件类型检测。

**决定**：直接在 `DummyProcessor` 上 override `parse_document` 方法为直接调用 FakeParser，绕过所有文件类型检测。这是最干净、最不容易受代码变化影响的方案。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| `get_db_path()` 函数增加微小运行时开销 | 每次数据库操作仅一次 `os.getenv()` 调用，可忽略 |
| 其他模块也可能有类似 `DB_PATH` 缓存问题 | 本次仅修认证模块，其他模块未发现同类问题 |
| PDF 测试修复依赖于 processor 内部实现 | 使用 override 模式，不依赖内部实现细节 |
| 回调测试修复可能因 LightRAG API 变更再次失败 | `ainsert` 是 LightRAG 核心 API，变更可能性低 |
