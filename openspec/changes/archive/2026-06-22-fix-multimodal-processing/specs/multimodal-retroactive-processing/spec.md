# multimodal-retroactive-processing

对已入库但未完成多模态处理的文档，支持回溯触发 VLM 描述生成和实体提取。

## ADDED Requirements

### Requirement: Reprocess multimodal endpoint
系统 SHALL 提供 `POST /api/kb/{kb_name}/reprocess-multimodal` 端点，对指定 KB 中未完成多模态处理的文档进行回溯处理。

#### Scenario: Successful reprocess request
- **WHEN** 管理员调用 `POST /api/kb/6.21/reprocess-multimodal`
- **AND** KB `6.21` 中存在 `multimodal_processed != true` 的文档
- **THEN** 返回 `{"status": "queued", "total": <N>, "message": "..."}`
- **AND** 后台开始逐个处理文档的多模态内容

#### Scenario: No documents need reprocessing
- **WHEN** 管理员调用 `POST /api/kb/{kb_name}/reprocess-multimodal`
- **AND** KB 中所有文档的 `multimodal_processed` 均为 `true`
- **THEN** 返回 `{"status": "ok", "total": 0, "message": "所有文档已完成多模态处理"}`

### Requirement: Reprocess re-parses documents
回溯处理 SHALL 对每个需要处理的文档重新调用解析流程，优先使用解析缓存。

#### Scenario: Parse cache hit
- **WHEN** 文档的原始文件存在于 `./uploads/` 目录
- **AND** 解析缓存（parse_cache KV）中存在该文件的缓存条目
- **THEN** 解析阶段直接返回缓存的 `content_list`，不重新调用 MinerU
- **AND** 仅处理 `content_list` 中的多模态条目（图片/表格/公式）

#### Scenario: Original file missing
- **WHEN** 文档的原始文件在 `./uploads/` 和原路径均不存在
- **THEN** 跳过该文档，记录 warning 日志
- **AND** 不中断其他文档的处理

### Requirement: Reprocess skips text insertion
回溯处理 SHALL NOT 重新插入文本内容到 LightRAG，仅处理多模态条目。

#### Scenario: Only multimodal items processed
- **WHEN** 对已入库文档执行回溯处理
- **THEN** 不调用 `insert_text_content()` 或 `ainsert()`
- **AND** 仅调用 `_process_multimodal_content()` 处理图片/表格/公式条目
- **AND** 完成后标记 `multimodal_processed = true`

### Requirement: Reprocess respects processor configuration
回溯处理 SHALL 仅处理当前 KB 实例中已注册的多模态处理器对应的内容类型。

#### Scenario: Only image processing enabled
- **WHEN** KB 实例仅注册了 `ImageModalProcessor`（`enable_table_processing=false`）
- **AND** 文档包含图片和表格条目
- **THEN** 仅处理图片条目，表格条目被跳过

### Requirement: Reprocess authorization
回溯处理端点 SHALL 要求管理员权限。

#### Scenario: Non-admin access denied
- **WHEN** 非管理员用户调用 `POST /api/kb/{kb_name}/reprocess-multimodal`
- **THEN** 返回 HTTP 403
