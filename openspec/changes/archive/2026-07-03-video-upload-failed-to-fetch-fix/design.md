## Context

当前上传链路涉及三层组件：

```
Browser (fetch/FormData) → Nginx (proxy_pass) → Uvicorn/FastAPI (POST /upload)
```

**现状问题**：

1. **Nginx** `proxy_read_timeout = 300s`：从开始接收请求到后端返回响应头的总时限。以 10Mbps 上行速度上传 500MB 视频需 ~400s，超过此值即被切断。
2. **前端** `api.uploadFile()` 裸调 `fetch()`，无 `AbortController` 超时控制。浏览器抛出的 "Failed to fetch" 是笼统的 `TypeError`，用户无法得知是超时、网络中断还是服务器问题。
3. **后端** `POST /upload` 用 `await file.read()` 将整个文件读入内存后再写磁盘、算哈希、注册 PG，最后才返回响应。虽 Starlette 已将上传流式 Spool 到临时文件，但强制全量读入内存对大文件（500MB+）有 OOM 风险。

本设计覆盖 P0（Nginx 超时）、P1（前端超时+错误分类）、P2（后端流式写入）。P3（分片上传）留到后续独立 change。

## Goals / Non-Goals

**Goals:**
- 500MB 以内视频文件在 10Mbps 上行带宽下可稳定上传
- 用户收到可操作的中文错误提示（而非 "Failed to fetch"）
- 后端不再因大文件上传导致内存暴涨

**Non-Goals:**
- 分片上传 / 断点续传（留作 P3，独立 change）
- 上传进度条（可选增强，本次不做）
- 修改 `uploadFolder`、`uploadContent`、`uploadUrl` 端点（它们不涉及大文件）

## Decisions

### Decision 1: Nginx 超时设为 600s

**选择**：`proxy_read_timeout = 600s`，`proxy_send_timeout = 600s`

**计算依据**：
```
500MB ÷ 1.25MB/s (10Mbps) = 400s 上传时间
400s + 5s 服务器处理 + 5s 网络抖动 ≈ 410s
600s ≈ 1.5× 安全系数，覆盖大多数家庭宽带场景
```

**备选方案**：

| 方案 | 值 | 优点 | 缺点 |
|------|------|------|------|
| 当前值 | 300s | — | 200MB+ 视频必定超时 |
| **选中** | **600s** | 覆盖 500MB/10Mbps 场景 | 长连接占用 nginx worker |
| 备选 | 900s | 更大余量 | 过长的超时掩盖真正的服务端卡死问题 |

慢客户端连接 nginx worker 的时间从 300s 提升到 600s。当前部署规模（单机、少量并发上传）下，worker 占用增加可忽略。

### Decision 2: 前端用 AbortController 实现 600s 超时

**选择**：在 `api.uploadFile()` 和 `api.uploadFiles()` 中创建 `AbortController`，`setTimeout` 600s 后 `abort()`，将 `signal` 传入 `fetch()`。

**备选方案**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| **AbortController + fetch** | 现代标准 API，与现有 fetch 模式一致 | 需手动管理 timeout 计时器 |
| XMLHttpRequest + `timeout` 属性 | 原生超时支持 | API 老旧，与项目 fetch 风格不一致 |
| 仅改善错误提示 | 改动最小 | 不解决根本问题，浏览器仍等 300s+ 才报错 |

**错误分类逻辑**：
```javascript
catch (err) {
  if (err.name === 'AbortError')
    msg = '上传超时：文件过大或网络较慢，请重试'
  else if (err.message === 'Failed to fetch')
    msg = '网络错误：上传中断，请检查网络连接后重试'
  else
    msg = `上传失败：${err.message}`
}
```

### Decision 3: 后端用 shutil.copyfileobj 流式写入替代 await file.read()

**选择**：不调 `await file.read()`，改用 `shutil.copyfileobj(file.file, dest_fd)` 从 Starlette 的 SpooledTemporaryFile 流式拷贝到目标文件。

**当前代码路径**（`knowledge.py` L184-185）：
```python
content = await file.read()        # 全部读入内存 (500MB → 500MB RAM)
file_path.write_bytes(content)      # 写盘
```

**改进后路径**：
```python
with open(file_path, 'wb') as dest:
    shutil.copyfileobj(file.file, dest)  # 块级拷贝 (默认 64KB 块)
# file.file 是 SpooledTemporaryFile — Starlette 已将上传内容 spool 到磁盘/内存
```

**效果对比**：

| 指标 | 当前 (read) | 改进后 (copyfileobj) |
|------|------------|---------------------|
| 内存峰值 | ~文件大小 | ~64KB (块大小) |
| 500MB 文件内存 | ~500MB | 几乎不变 |
| TTFB | 无改善（Starlette 已缓冲） | 无改善（同上） |
| OOM 风险 | 高 | 低 |

**注意**：Starlette 的 `UploadFile` 内部已使用 `SpooledTemporaryFile`（默认阈值 1MB，超过即落盘）。`await file.read()` 的耗时主要是在内存中分配大对象，而非网络 I/O。流式拷贝解决的是**内存安全**问题，TTFB 改善有限。

**哈希计算仍保留在响应前**，因为：
- SHA256 通过分块读取计算，内存友好
- 耗时短（500MB ~2s），不显著影响响应时间
- 需要在前端返回之前完成去重检查，以返回 409 给前端

### Decision 4: 不改动 uploadFolder / uploadContent / uploadUrl

这三个端点不处理大文件（文本内容、URL、文件夹路径），不存在超时问题。保持改动范围最小。

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 600s nginx 超时导致 worker 长时间被慢客户端占用 | 并发能力下降 | 当前单机部署并发上传极少，实际影响可忽略。监控 nginx `stub_status` 可观测 |
| AbortController 在旧浏览器不支持 | 老浏览器无超时控制 | AbortController 在 Chrome 66+ / Firefox 57+ / Safari 12.1+ 均支持，覆盖 98%+ 用户 |
| `shutil.copyfileobj` 对超大文件（>2GB）仍慢 | 极端大文件场景 | 属 P3 分片上传范围。500MB 以内测试通过即可 |
| 流式写入完成后立即返回，去重哈希计算仍在响应前阻塞 | TTFB 仍含 ~2s 哈希时间 | 可接受。若未来需要进一步优化，可将哈希+去重移到后台队列 |

## Open Questions

1. **是否需要配置化超时值**？当前硬编码 600s。可考虑通过环境变量 `UPLOAD_TIMEOUT_SECONDS` 控制，但 YAGNI — 等有实际需求再加。
2. **是否需要 upload 端点单独的 nginx location**？例如 `/api/upload` 独立配置更长超时、更大 body size。当前全局 `/api/` 的 600s/500m 已足够覆盖所有端点，拆分为两个 location 增加维护成本。
