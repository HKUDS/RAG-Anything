# Upload Large File Resilience

## Purpose

Ensure the upload pipeline can handle large files (up to 500MB) without timeout or memory issues across all layers: Nginx proxy, Vite dev server, frontend fetch, and backend streaming.

## Requirements

### Requirement: 前端上传请求超时控制

系统 SHALL 在 `api.uploadFile()` 和 `api.uploadFiles()` 函数中，使用 `AbortController` 为每个上传请求设定 600 秒超时，超时后主动 abort 请求并抛出可识别的中文错误信息。

#### Scenario: 上传在超时时间内完成

- **WHEN** 用户上传一个文件且上传+服务器处理在 600 秒内完成
- **THEN** 请求正常返回 `task_id` 和 `status: "queued"`
- **AND** 前端正常显示上传成功状态

#### Scenario: 上传超时

- **WHEN** 用户上传一个大文件且 600 秒内未收到服务器响应
- **THEN** 系统 SHALL 通过 `AbortController.signal` abort 该 fetch 请求
- **AND** 系统 SHALL 抛出错误信息 "上传超时：文件过大或网络较慢，请重试"
- **AND** 前端 SHALL 在文件列表中显示该文件的超时错误状态

#### Scenario: 上传过程中网络中断

- **WHEN** 上传请求因网络中断导致 fetch 抛出 `TypeError`
- **THEN** 系统 SHALL 将 "Failed to fetch" 转换为中文错误 "网络错误：上传中断，请检查网络连接后重试"

### Requirement: Nginx 代理超时与大文件上传对齐

Nginx 反向代理的 `proxy_read_timeout` 和 `proxy_send_timeout` SHALL 设置为 600 秒，与前端 `AbortController` 超时保持一致，确保 500MB 以内文件在 10Mbps 上行带宽下可完整上传。

#### Scenario: 大文件上传不触发 Nginx 超时

- **WHEN** 用户上传一个 500MB 的视频文件且上行带宽为 10Mbps
- **THEN** Nginx SHALL 在传输和等待后端响应的整个过程中不主动断开连接
- **AND** 后端 SHALL 在文件传输完成后的合理时间内返回响应

### Requirement: 后端上传端点流式接收

`POST /api/upload` 端点 SHALL 使用流式方式接收上传文件，将文件内容边接收边写入磁盘，而非通过 `await file.read()` 将整个文件读入内存后才响应。

#### Scenario: 流式写入后立即返回

- **WHEN** 文件上传请求到达服务器
- **THEN** 系统 SHALL 以流式方式将文件内容写入 `./uploads/` 目录
- **AND** 文件写入完成后 SHALL 立即返回 `task_id` 和 `status: "queued"`
- **AND** 响应时间 SHALL 不随文件大小线性增长

#### Scenario: 哈希计算异步执行

- **WHEN** 文件流式写入磁盘完成
- **THEN** 系统 SHALL 在返回响应之前计算文件哈希用于去重检查
- **AND** 若哈希计算可异步完成而不阻塞响应，SHALL 延迟到后台队列处理

#### Scenario: 流式写入磁盘空间不足

- **WHEN** 文件流式写入过程中磁盘空间不足
- **THEN** 系统 SHALL 中止写入并清理已写入的部分文件
- **AND** 返回 HTTP 507 (Insufficient Storage) 错误

### Requirement: 去重检查兼容流式接收

文件去重检查（`_compute_file_hash` + `_is_file_being_processed` + `pg_register_upload`）SHALL 在流式写入完成后仍然正确执行，确保重复文件在上传阶段即被拦截。

#### Scenario: 重复文件流式上传后被拦截

- **WHEN** 用户上传一个与已存在文件内容相同的文件（相同哈希）
- **THEN** 系统 SHALL 在流式写入和哈希计算后检测到重复
- **AND** 返回 HTTP 409 错误
- **AND** 清理新写入的重复文件
