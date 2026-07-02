## ADDED Requirements

### Requirement: 文档列表去重

系统 SHALL 在 `list_documents` API 响应中对同一逻辑文档只返回一条记录。

当 `processing_tasks`（内存）和 `kv_store_doc_status`（磁盘）中存在指向同一原始文件的条目时，系统 SHALL 合并为单一文档条目。

#### Scenario: 上传中的文档去重

- **WHEN** 文档正在上传处理中，`processing_tasks` 中有 `file: "测试.docx"` 的任务记录
- **AND** `kv_store_doc_status` 中存在 `file_path: "abc12345_测试.docx"` 的历史记录
- **THEN** `list_documents` 只返回一条文档记录，优先显示处理中的任务状态

#### Scenario: 已完成文档去重

- **WHEN** 文档处理已完成，`processing_tasks` 中的任务状态为 `completed`
- **AND** `kv_store_doc_status` 中存在对应的 `file_path` 条目
- **THEN** `list_documents` 只返回一条文档记录，状态为已完成
- **AND** 已完成的 `processing_tasks` 条目在本次响应后不被再次返回

### Requirement: Hash 前缀文件名识别与剥离

系统 SHALL 识别并剥离由 `secrets.token_hex(4)` 生成的 8 位十六进制前缀（格式：`^[0-9a-f]{8}_`），从 `593dbd4b_测试.docx` 提取原始文件名 `测试.docx`。

#### Scenario: 正常 hash 前缀剥离

- **WHEN** 输入文件名为 `abc12345_report.pdf`
- **THEN** 返回原始文件名 `report.pdf`

#### Scenario: 无前缀文件名原样返回

- **WHEN** 输入文件名为 `测试.docx`（无 hash 前缀）
- **THEN** 返回原始文件名 `测试.docx`

#### Scenario: 非 hex 前缀不被剥离

- **WHEN** 输入文件名为 `myfolder_报告.pdf`（前缀非 8 位 hex）
- **THEN** 返回原始文件名 `myfolder_报告.pdf`

### Requirement: 已完成任务条目的自动清理

系统 SHALL 在 `list_documents` 响应构建前，从 `processing_tasks` 字典中移除所有状态为 `completed` 或 `failed` 的任务条目。

#### Scenario: 已完成任务被清理

- **WHEN** `processing_tasks` 中存在 `status: "completed"` 的任务
- **AND** 前端轮询调用 `list_documents`
- **THEN** 该已完成任务从 `processing_tasks` 中移除
- **AND** 后续 `list_documents` 调用不再返回该任务

#### Scenario: 处理中任务不受影响

- **WHEN** `processing_tasks` 中存在 `status: "processing"` 的任务
- **AND** 调用 `list_documents`
- **THEN** 该任务保留在 `processing_tasks` 中
- **AND** 文档列表中显示为"处理中"状态
