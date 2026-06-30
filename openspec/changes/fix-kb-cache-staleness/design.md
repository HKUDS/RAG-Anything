## Context

`raganything/services/kb_service.py` 中的 `kb_instances: dict[str, RAGAnything]` 是 KB 实例的全局缓存。子进程（`process_worker.py`）完成文档处理后直接写入磁盘存储文件，服务端通过以下路径感知变更：

1. 上传成功路径：`_process_uploaded_file` → `finalize_storages()` + `del kb_instances[name]`（line 505-512）
2. 上传失败路径：`except Exception` → `_fix_stuck_doc_status()`（line 521-525）

缺陷：路径 1 和 2 都依赖上传协程正常完成。如果进程在中间状态（如 status="handling"）被中断，两个路径都不会触发，缓存永久陈旧。

## Goals / Non-Goals

**Goals:**
- `get_kb()` 能自动检测磁盘数据比缓存新并重建
- 周期性自动修复卡在 "handling" 状态的文档
- 管理员可手动刷新 KB 缓存无需重启

**Non-Goals:**
- 不改变子进程处理流程
- 不增加分布式缓存（Redis 等）
- 不修改 `_process_uploaded_file` 的上传逻辑

## Decisions

### D1: 缓存新鲜度检测——doc_status mtime

**选择**：在 `get_kb()` 中，如果 `name` 已在 `kb_instances` 中，检查 `kv_store_doc_status.json` 的 `mtime`。若磁盘 mtime > 缓存创建时间，执行 `finalize_storages()` + `del kb_instances[name]` + 重新创建实例。

```python
async def get_kb(name: str = None) -> RAGAnything:
    name = name or active_kb
    if name not in _kb_locks:
        _kb_locks[name] = asyncio.Lock()
    async with _kb_locks[name]:
        if name in kb_instances:
            # 检查磁盘是否比缓存新
            doc_status_path = Path(kb_dir(name)) / "kv_store_doc_status.json"
            if doc_status_path.exists():
                disk_mtime = doc_status_path.stat().st_mtime
                cache_age = time.time() - _kb_cache_time.get(name, 0)
                if disk_mtime > _kb_cache_time.get(name, 0):
                    # 磁盘已更新，清除缓存重建
                    try:
                        await kb_instances[name].finalize_storages()
                    except Exception:
                        pass
                    del kb_instances[name]
                    kb_logger.info(f"[KB] 缓存过期重建: {name}")
        if name not in kb_instances:
            # ... 现有创建逻辑 ...
            kb_instances[name] = instance
            _kb_cache_time[name] = time.time()
    return kb_instances[name]
```

**替代方案**：
- A) 固定 TTL（如 60 秒）→ 拒绝：无变更时也重建，浪费资源
- B) inotify 文件监听 → 拒绝：Windows 兼容性差，过度设计

**理由**：mtime 检测精确、零额外开销、跨平台。

### D2: 周期恢复扫描——asyncio.create_task + 5分钟间隔

**选择**：服务器启动时启动后台 asyncio 任务，每 300 秒扫描所有 KB 的 `kv_store_doc_status.json`，修复 status="handling" 的文档。

```python
async def _recover_stuck_documents_loop():
    """后台任务：定期扫描并修复卡住的文档状态"""
    while True:
        await asyncio.sleep(300)
        try:
            meta = load_kb_meta()
            for kb_name in meta:
                status_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
                if not status_path.exists():
                    continue
                data = json.loads(status_path.read_text(encoding="utf-8"))
                for doc_id, info in data.items():
                    if info.get("status") == "handling" and info.get("metadata", {}).get("processing_end_time"):
                        info["status"] = "completed"
                        kb_logger.info(f"[Recovery] 修复卡住文档: {kb_name}/{doc_id[:16]}")
                # 写回并清除缓存
                status_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                if kb_name in kb_instances:
                    del kb_instances[kb_name]
        except Exception as e:
            kb_logger.warning(f"[Recovery] 扫描异常: {e}")
```

**理由**：5 分钟间隔足够宽松，不影响性能；asyncio 任务在 FastAPI lifespan 中启动，随服务器生命周期管理。

### D3: 管理 API——POST /admin/reload-kb/{kb_name}

**选择**：新增端点，权限 `settings:write`。

```python
@router.post("/reload-kb/{kb_name}")
async def reload_kb(kb_name: str, current_user: dict = Depends(require_permission(Permission.SETTINGS_WRITE))):
    if kb_name in kb_instances:
        try:
            await kb_instances[kb_name].finalize_storages()
        except Exception:
            pass
        del kb_instances[kb_name]
        return {"status": "ok", "message": f"KB '{kb_name}' 缓存已清除"}
    return {"status": "skipped", "message": f"KB '{kb_name}' 不在缓存中"}
```

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| 周期扫描在大型部署（100+ KB）下可能耗时 | 扫描仅读取 doc_status JSON（~2KB/KB），100 KB ≈ 200KB，<1s |
| mtime 在容器/网络文件系统中可能不精确 | Python `os.path.getmtime` 返回系统时间，同一主机内可靠 |
| `del kb_instances[name]` 后旧引用可能仍在使用 | `get_kb()` 的 Lock 保证同一时刻只有一个协程创建实例 |

## Open Questions

1. **是否需要为 `_kb_cache_time` 持久化？** 当前为内存字典，服务器重启后自然清空，这是期望行为。
