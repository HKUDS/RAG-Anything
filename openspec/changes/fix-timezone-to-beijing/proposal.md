## Why

所有文档处理时间戳（`updated_at`、`created_at`）使用 UTC 时区（`+00:00`），导致前端显示的更新时间比北京时间少 8 小时。例如：北京时间 15:20 上传的文档显示为 07:20，造成用户困惑。需统一改为北京时间（UTC+8）。

## What Changes

- 创建统一的北京时间工具函数 `beijing_now()`，返回 `YYYY-MM-DDTHH:MM:SS+08:00` 格式
- 替换 `raganything/processor/doc_processor.py` 中 3 处 UTC 时间戳为北京时间
- 替换 `raganything/processor/multimodal_processor.py` 中 1 处 UTC 时间戳为北京时间
- 替换 `raganything/processor/chunk_processor.py` 中 1 处 UTC 时间戳为北京时间

## Capabilities

### New Capabilities

- `beijing-timezone`: 统一时间戳工具函数，确保所有模块使用北京时间（UTC+8）生成 `updated_at` / `created_at` 字段

### Modified Capabilities

<!-- No existing specs govern timezone behavior. -->

## Impact

- **Affected code**: `raganything/processor/doc_processor.py`（`_current_doc_status_timestamp` 方法及 2 处 `updated_at`）、`raganything/processor/multimodal_processor.py`（1 处 `updated_at`）、`raganything/processor/chunk_processor.py`（1 处 `updated_at`）
- **New file**: 在 `raganything/utils/` 或 `raganything/processor/` 中新增北京时间工具函数
- **No API changes**: 只改变时间戳值，不改变字段名或接口格式
- **No DB migration required**: `doc_status` 使用 JSON 存储，无需 schema 变更
