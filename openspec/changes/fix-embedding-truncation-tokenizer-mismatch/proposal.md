## Why

多模态内容（VLM 图片描述、LLM 表格分析）生成的 chunk 内容在嵌入阶段（`text-embedding-v3`）因超长被千问 API 拒绝（8192 token 上限），导致整批 75 条嵌入失败，触发慢速逐条回退。

根因是 **tokenizer 计数不一致**：LightRAG 使用 `o200k_base`（gpt-4o-mini）tokenizer，对中文文本的 token 计数约为千问 API 实际 tokenizer 的 **一半**。LightRAG 数出 4000 token 的内容，千问 API 实际计数 8000+，超过 8192 上限。

此前基于 `o200k_base` 的截断阈值（6000 token）完全无效——等 LightRAG 数到 6000 时，千问早已超过 12000 token。

## What Changes

- **字符级截断**：所有 chunk 内容在嵌入前以 8000 字符硬截断，不依赖 tokenizer 计数
- **逐条容错嵌入**：批量嵌入改为逐条调用，单条嵌入失败只跳过该条，不影响其余 chunk
- **覆盖全路径**：批量路径（`processor.py`）和逐条回退路径（`modalprocessors.py`）均已覆盖

## Capabilities

### New Capabilities
- `chunk-embedding-resilience`: 嵌入截断使用字符级限制（消除 tokenizer 不匹配）+ 逐条容错（单条失败不拖垮整批）

### Modified Capabilities
<!-- None. -->

## Impact

- `raganything/processor.py`: `_convert_to_lightrag_chunks_type_aware()` 截断逻辑 + `_store_chunks_to_lightrag_storage_type_aware()` 逐条容错
- `raganything/modalprocessors.py`: `_create_entity_and_chunk()` 截断逻辑
- `.env`: `PROCESS_TIMEOUT=86400` 防止长时间处理被误杀
