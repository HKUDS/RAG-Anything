## ADDED Requirements

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
