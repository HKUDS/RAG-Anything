## Why

LightRAG 的 `DEFAULT_SUMMARY_LANGUAGE` 默认值为 `"English"`。当 RAGAnything 初始化 LightRAG 实例时未显式设置 `addon_params.language`，LightRAG 在 hybrid/local/global/naive/mix 等所有非 RRF 查询模式中，用英文关键词去检索中文实体库，导致关键词与实体名语言不匹配，返回 0 结果。用户被迫只能使用 RRF 融合模式，而无法使用 LightRAG 内置的 hybrid 等传统查询模式。

## What Changes

- 在 `raganything/raganything.py` 的 LightRAG 初始化阶段，向 `addon_params` 注入 `language` 参数，默认值为 `"Chinese"`
- `language` 参数通过环境变量 `LIGHTRAG_LANGUAGE` 可配置，支持 "Chinese" / "English" / 其他语言
- 同时调整 `raganything/config.py` 新增 `lightrag_language` 配置项

## Capabilities

### New Capabilities

- `lightrag-language-config`: LightRAG 查询语言配置——支持通过环境变量或配置项设置 LightRAG 的关键词提取和摘要语言，确保中文查询能正确匹配中文实体库

## Impact

- **Affected code**: `raganything/raganything.py` (line ~423-429，向 `addon_params` 注入 `language`)
- **Affected config**: `raganything/config.py` (新增 `lightrag_language` 字段)
- **Affected query modes**: hybrid, local, global, naive, mix（所有走 LightRAG 内置查询的模式）
- **Backward compatibility**: 完全兼容。默认值从 "English" 变为 "Chinese"，对已有中文知识库是修复，对英文知识库可通过配置切回 "English"
- **No breaking changes**
