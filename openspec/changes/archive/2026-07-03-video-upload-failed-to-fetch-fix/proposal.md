## Why

大视频文件（如"机油加注.mp4"）上传时浏览器端报 "Failed to fetch"，用户无法成功上传视频知识。根因是三层超时缺口——前端无超时控制、后端全量读内存后才响应、Nginx 代理 300s 超时——导致上传传输阶段就已超时，服务器永远收不到完整请求。视频类文件动辄 200MB+，在典型家庭宽带上行速度下传输本身就需要 4-5 分钟，撞上 5 分钟超时墙是必然结果。

## What Changes

- **P0: Nginx 代理超时提升** — `proxy_read_timeout` 和 `proxy_send_timeout` 从 300s 提升到 600s，覆盖 500MB 以内视频的完整上传窗口
- **P1: 前端上传超时控制** — `api.uploadFile()` 增加 `AbortController`，设定 600s 超时，超时后主动 abort 并给出明确的中文错误提示（"上传超时：文件过大或网络较慢，请重试"），替代泛泛的 "Failed to fetch"
- **P2: 后端流式接收** — 不再 `await file.read()` 全量读入内存后才返回，改用流式写入磁盘后立即返回 `task_id`，将 TTFB 从"传输+处理时间"缩短到"秒级"；哈希校验后移到异步队列

## Capabilities

### New Capabilities
- `upload-large-file-resilience`: 大文件上传的超时韧性——前端可控超时 + 明确错误反馈、后端流式接收即时响应、Nginx 代理超时对齐。覆盖从网络层到应用层的完整超时防线。

### Modified Capabilities
- `upload-failure-detection`: 将上传失败的错误信息从泛泛的浏览器原生 "Failed to fetch" 提升为可操作的中文提示（"上传超时"、"网络错误"、"文件过大"等），使用户能根据错误类型采取不同应对措施。

## Impact

| 层级 | 文件 | 变更类型 |
|------|------|---------|
| Nginx | `nginx.conf` | `proxy_read_timeout` / `proxy_send_timeout` 300→600 |
| 前端 | `frontend/src/utils/api.js` | `uploadFile()` / `uploadFiles()` 加 `AbortController` 超时+错误分类 |
| 后端 | `raganything/routers/knowledge.py` | `/upload` 端点改为流式写入、哈希迁移到后台 |
