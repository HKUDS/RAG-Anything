## Why

KB 实例在 `kb_instances` 字典中无限期缓存，唯一失效路径是上传成功后的 `del kb_instances[name]`（[kb_service.py:511](raganything/services/kb_service.py#L511)）。当子进程异常退出、服务器重启、或上传流程在 status="handling" 阶段中断时，缓存永不失效，导致前端显示"入库中"（即使磁盘数据完整），以及查询返回空结果（内存索引陈旧）。当前唯一修复手段是重启服务器。

## What Changes

- **KB 缓存自动失效**：`get_kb()` 每次调用时检查 `kv_store_doc_status.json` 的磁盘 mtime，若磁盘比内存缓存新则自动重建实例
- **卡住文档自动恢复**：服务器启动时和每 5 分钟周期性扫描所有 KB，将 status="handling" 且 `processing_end` 已写入的文档自动标记为 completed，并清除对应 KB 缓存
- **手动刷新 API**：新增 `POST /admin/reload-kb/{kb_name}` 端点，管理员可手动清除指定 KB 缓存触发重新加载

## Capabilities

### New Capabilities
- `kb-cache-invalidation`: 每次 `get_kb()` 调用基于磁盘 mtime 校验缓存新鲜度，自动过期重建
- `kb-stuck-recovery`: 启动时 + 周期性扫描所有 KB，自动修复 status="handling" 的卡住文档
- `kb-admin-reload`: 管理员 API 端点手动清除 KB 缓存

### Modified Capabilities
无。均为新增能力，不修改现有 spec 行为。

## Impact

- **受影响代码**：
  - `raganything/services/kb_service.py`：`get_kb()` 增加 mtime 检测、新增 `_recover_stuck_documents()`、新增 `_start_stuck_recovery_task()`、`_fix_stuck_doc_status()` 移到周期任务中
  - `raganything/routers/admin.py`：新增 `POST /admin/reload-kb/{kb_name}` 端点（需要 `settings:write` 权限）
- **受影响 API**：新增 1 个管理端点
- **受影响依赖**：无
- **向后兼容**：完全兼容。`get_kb()` 签名不变，行为增强（更准确地反映磁盘状态）
- **风险**：低。mtime 检测仅增加一次 `os.path.getmtime` 调用（<1ms）；周期扫描仅遍历 KB 元数据文件
