# Test Integration Fixes

## Purpose

Fix pre-existing integration test failures by ensuring mock objects implement the complete interface required by the code under test, and by correctly targeting monkeypatches at the actual import location used by consuming modules.

## Requirements

### Requirement: Callback integration test mocks complete LightRAG interface
`test_process_document_emits_callbacks` 测试中的 `FakeLightRAG` SHALL 实现被测试代码路径所调用的所有 LightRAG 方法。

#### Scenario: FakeLightRAG supports ainsert method
- **WHEN** `processor.process_document_complete` 调用 `insert_text_content`
- **THEN** `insert_text_content` 调用 `lightrag.ainsert()`
- **AND** `FakeLightRAG.ainsert()` 存在且不抛出 `AttributeError`

#### Scenario: Document processing emits all expected callbacks
- **WHEN** 完整的文档处理流程执行
- **THEN** 回调事件列表包含 `text_insert_start`、`text_insert_complete`、`document_complete`

### Requirement: Parser wiring test bypasses PDFium file validation
`test_processor_parse_document_uses_selected_parser` 测试 SHALL 在 `DummyProcessor` 上直接替换 `parse_document` 方法，绕过 PDFium 的文件格式验证，直接调用 FakeParser。

#### Scenario: parse_document returns FakeParser output without PDFium
- **WHEN** `DummyProcessor.parse_document` 被调用且已 Mock `get_parser`
- **THEN** 方法不尝试通过 PDFium 打开 PDF 文件
- **AND** 返回 FakeParser 的内容列表

#### Scenario: Parser selection is validated
- **WHEN** `get_parser` 被调用来获取解析器
- **THEN** `parser_name` 参数等于配置的 parser 类型（如 `"paddleocr"`）
- **AND** 解析器仅被实例化一次（后续调用使用缓存）

#### Scenario: Cached parser is reused
- **WHEN** `parse_document` 被调用第二次
- **THEN** `get_parser` 不被重复调用（使用缓存的解析器实例）
