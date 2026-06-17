## Why

文档处理时表格 chunk 的内容模板将 LLM 生成的可读描述（`Analysis`）放在原始 bbox 坐标数据（`Structure`）之后。由于 `Structure` 包含大量的坐标 JSON，`Analysis` 在实际 chunk 内容中的位置极靠后，且往往超过 LLM 上下文的有效注意力窗口。导致 RRF 检索返回的表格 chunk 对 LLM 而言等同于不可解析的裸数据，无法从中正确区分"毕业设计答辩→13216"和"开题答辩→13220"。

## What Changes

- **模板重排**: 修改 `prompt.py` 和 `prompts_zh.py` 中的 `table_chunk` 模板，将 `Analysis` 字段移到 `Structure` 字段**之前**，确保 LLM 首屏即可看到可读描述
- **结构压缩**: 对 `Structure` 中的表格单元格数据做简化——仅保留 `text` 和行列索引，去掉 `bbox` 坐标、`row_header`、`fillable` 等冗余字段，大幅缩减体积
- **兜底格式**: 当 `table_body` 超过 2000 字符时，对 `Structure` 做截断并标注 `（表格数据过长，已截断）`

## Capabilities

### New Capabilities
- `table-chunk-readability`: 表格 chunk 可读性优化 —— 调整模板字段顺序和结构，确保 LLM 生成的可读表格分析在 chunk 中的优先级高于原始坐标数据

### Modified Capabilities
<!-- No existing specs affected -->

## Impact

- **文件**: `raganything/prompt.py` — `table_chunk` 模板
- **文件**: `raganything/prompts_zh.py` — `table_chunk` 中/英模板
- **文件**: `raganything/processor.py` — `_apply_chunk_template()` 中 table 分支的 `table_body` 预处理（结构简化）
- **数据影响**: 已处理文档需 `force_reprocess=true` 重新处理才能应用新模板
