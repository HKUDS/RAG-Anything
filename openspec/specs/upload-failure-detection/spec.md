## ADDED Requirements

### Requirement: Worker 子进程正确报告所有失败

系统 SHALL 在 worker 子进程 (`process_worker.py`) 中，当文档处理后的 doc_status 为 `failed` 或 `chunks_count` 为 0 时，以非零 exit code 退出。

#### Scenario: doc_status 为 failed 时 worker exit 1

- **WHEN** LightRAG 内部将文档的 doc_status 标记为 `"failed"`
- **AND** worker 处理完成后检查 doc_status
- **THEN** worker SHALL 以 exit code 1 退出
- **AND** worker SHALL 在 stdout 输出包含 `ERROR` 的消息

#### Scenario: chunks_count 为 0 时 worker exit 1

- **WHEN** 文档处理完成后 doc_status 中 `chunks_count` 为 0
- **THEN** worker SHALL 以 exit code 1 退出（无论 status 字段为何值）

#### Scenario: 正常处理成功时 worker exit 0

- **WHEN** 文档处理完成后 doc_status 中 `status` 不为 `failed`
- **AND** `chunks_count > 0`
- **THEN** worker SHALL 以 exit code 0 退出

### Requirement: 主进程验证文档数据已写入

系统 SHALL 在 worker 子进程成功返回后，读取 `kv_store_doc_status.json` 验证对应文档的 `chunks_count > 0`，若验证失败则将任务标记为 `failed`。

#### Scenario: 文档数据验证通过

- **WHEN** worker 以 exit code 0 返回
- **AND** `kv_store_doc_status.json` 中存在匹配文件名的条目且 `chunks_count > 0`
- **THEN** 主进程将 `processing_tasks` 中的任务状态标记为 `completed`

#### Scenario: 文档数据验证失败

- **WHEN** worker 以 exit code 0 返回
- **AND** `kv_store_doc_status.json` 中不存在匹配条目或 `chunks_count` 为 0
- **THEN** 主进程将 `processing_tasks` 中的任务状态标记为 `failed`

### Requirement: process_document_complete 数据持久化

系统 SHALL 在 `process_document_complete` 方法中，`insert_text_content` 完成后调用 `_insert_done()` 确保 entity/relation 数据持久化到磁盘。

#### Scenario: docx 文档处理后数据持久化

- **WHEN** `process_document_complete` 完成 `insert_text_content` 调用
- **THEN** 系统 SHALL 调用 `self.lightrag._insert_done()` 持久化数据
- **AND** 该调用与 `insert_content_list` 路径的行为保持一致

### Requirement: finalize_storages 异常可见

系统 SHALL 在 `finalize_storages()` 调用失败时输出 warning 级别日志，不静默吞掉异常。

#### Scenario: finalize_storages 异常日志

- **WHEN** `kb_instances[name].finalize_storages()` 抛出异常
- **THEN** 系统 SHALL 记录 warning 日志包含异常信息
- **AND** 继续执行后续清理逻辑

### Requirement: 前端上传错误分类与中文提示

系统 SHALL 在前端上传流程中对不同类型的 fetch 错误进行分类，将浏览器原生错误信息转换为用户可理解、可操作的中文提示。

#### Scenario: 超时错误

- **WHEN** `AbortController` 触发超时 abort 导致 `AbortError`
- **THEN** 前端 SHALL 显示 "上传超时：文件过大或网络较慢，请重试"

#### Scenario: 网络中断错误

- **WHEN** fetch 抛出 `TypeError` 且错误信息为 "Failed to fetch"
- **THEN** 前端 SHALL 显示 "网络错误：上传中断，请检查网络连接后重试"

#### Scenario: 服务器拒绝（文件过大）

- **WHEN** 服务器返回 HTTP 413 (Content Too Large)
- **THEN** 前端 SHALL 显示 "文件过大：超过服务器上传限制，请压缩后重试"

#### Scenario: 服务器拒绝（重复文件）

- **WHEN** 服务器返回 HTTP 409 (Conflict)
- **THEN** 前端 SHALL 显示 "文件重复：该文件已存在或正在处理中"

#### Scenario: 服务器内部错误

- **WHEN** 服务器返回 HTTP 500+
- **THEN** 前端 SHALL 显示 "服务器错误：上传失败，请稍后重试"

#### Scenario: 其他未知错误

- **WHEN** 发生其他非预期错误
- **THEN** 前端 SHALL 显示包含原始错误信息的提示 "上传失败：{原始错误消息}"
