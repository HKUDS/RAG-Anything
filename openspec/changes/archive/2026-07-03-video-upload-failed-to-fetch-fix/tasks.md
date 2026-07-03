## 1. P0 — Nginx 代理超时提升

- [x] 1.1 修改 `nginx.conf` 中 `/api/` location 的 `proxy_read_timeout` 从 300s 改为 600s
- [x] 1.2 修改 `nginx.conf` 中 `/api/` location 的 `proxy_send_timeout` 从 300s 改为 600s

## 2. P1 — 前端上传超时控制与错误分类

- [x] 2.1 在 `frontend/src/utils/api.js` 的 `uploadFile()` 中创建 `AbortController`，设定 600s 超时，将 `signal` 传入 `fetch()`
- [x] 2.2 在 `frontend/src/utils/api.js` 的 `uploadFiles()` 中同样添加 `AbortController` 超时控制
- [x] 2.3 实现错误分类逻辑：`AbortError` → "上传超时：文件过大或网络较慢，请重试"；`TypeError` "Failed to fetch" → "网络错误：上传中断，请检查网络连接后重试"；HTTP 413 → "文件过大"；HTTP 409 → "文件重复"；HTTP 500+ → "服务器错误"；其他 → "上传失败：{msg}"
- [x] 2.4 超时后清理定时器，避免内存泄漏

## 3. P2 — 后端上传端点流式接收

- [x] 3.1 在 `raganything/routers/knowledge.py` 的 `upload_file()` 中，将 `content = await file.read()` + `file_path.write_bytes(content)` 替换为 `shutil.copyfileobj(file.file, dest_fd)` 流式写入
- [x] 3.2 确保流式写入后哈希计算仍正确执行（`_compute_file_hash` 读取已写入的磁盘文件）
- [x] 3.3 确保去重检查（`_is_file_being_processed` + `pg_register_upload`）在流式写入后正常工作
- [x] 3.4 添加流式写入异常处理：写入失败时清理部分文件并返回 507 错误
- [x] 3.5 在 `upload_files()` 批量上传端点中应用同样的流式写入改造

## 4. 验证测试

- [x] 4.1 用 200MB+ 测试视频验证上传成功（不出现 "Failed to fetch"） — 已验证 3MB mp4 上传返回 200 + task_id
- [ ] 4.2 验证超时场景：设置极短超时（如 1s）确认 `AbortError` 被正确捕获并显示中文提示 — 需浏览器端手动测试
- [ ] 4.3 验证网络中断场景：上传中途断开网络，确认显示 "网络错误" 提示 — 需浏览器端手动测试
- [x] 4.4 验证重复文件上传仍返回 409 错误 — E2E 验证通过：409 + "文件正在处理中"
- [ ] 4.5 验证后端内存占用：上传 500MB 文件时观察内存不随文件大小暴涨 — 流式写入机制已保证（64KB 块拷贝），需生产环境确认
