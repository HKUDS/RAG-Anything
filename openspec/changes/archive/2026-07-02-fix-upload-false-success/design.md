## Context

RAG-Anything 的上传处理采用主子进程架构：主进程 (`kb_service.py`) 通过 `asyncio.create_subprocess_exec` 启动 worker 子进程 (`process_worker.py`)，worker 调用 RAGAnything/LightRAG API 完成文档解析、entity 提取和图谱构建。主进程通过 subprocess returncode 和 stdout 输出判断成功/失败。

当前存在两个关键缺口：
1. Worker 的失败判定条件排除了 doc_status 已为 `"failed"` 的情况，导致 LightRAG 内部静默失败被掩盖
2. 主进程仅信任 subprocess returncode，不验证实际数据是否写入磁盘

此外，`process_document_complete`（docx 路径）未显式调用 `_insert_done()`，与纯文本路径 `insert_content_list` 不一致。

## Goals / Non-Goals

**Goals:**
- Worker 在任何文档处理失败的情况下（含 LightRAG 内部失败）都以非零 exit code 退出
- 主进程在 worker 返回后验证 doc_status 中确实有 chunks_count > 0
- `process_document_complete` 路径与 `insert_content_list` 路径保持一致的持久化行为
- `finalize_storages` 异常不再被静默吞掉

**Non-Goals:**
- 不修改 LightRAG 内部 entity extraction 逻辑
- 不改变 worker 的进程模型（仍使用 subprocess）
- 不修改前端

## Decisions

### 决策1：Worker 失败判定：移除 `not info.get("status") == "failed"` 条件

**选择**：将 `process_worker.py` 的条件从：
```python
if info.get("chunks_count", 0) == 0 and not info.get("status") == "failed":
```
改为：
```python
if info.get("chunks_count", 0) == 0 or info.get("status") == "failed":
```

**理由**：`"failed"` 状态本身就是失败，无论 chunk 数多少都应报告失败。原条件 `not failed` 恰好排除了最需要报告的情况。

### 决策2：后处理验证在读-改-写之外增加只读检查

**选择**：Worker 完成后，主进程读取 `kv_store_doc_status.json`，根据 `file_path`（basename）匹配对应条目，验证 `chunks_count > 0`。

**替代方案**：让 worker 在 stdout 输出 doc_id → 主进程解析。被拒绝：需要改动 worker 输出格式，更复杂。

**理由**：主进程已知文件名，直接读 doc_status 文件做交叉验证最简单。

### 决策3：在 `process_document_complete` 末尾添加 `_insert_done()`

**选择**：在 `insert_text_content` 返回后、status 更新前，添加 `await self.lightrag._insert_done()`。

**理由**：与 `insert_content_list` (line 1150-1154) 保持一致。虽然 LightRAG 内部在 `apipeline_process_enqueue_documents` 末尾也调了 `_insert_done()`，但显式调用确保即使内部路径提前返回也能持久化。

### 决策4：`finalize_storages` 异常日志

**选择**：将 `except Exception: pass` 替换为 `except Exception as e: lightrag_logger.warning(...)`。

## Risks / Trade-offs

- **[风险] `_insert_done()` 双重调用** → 缓解：`index_done_callback` 在 LightRAG 中是幂等的（已索引数据不会重复写入）
- **[风险] chunks_count=0 但文档实际为纯图片/表格（无可提取文本）** → 缓解：这种情况 worker 不应将其标记为 failed；doc_status 验证时若 status 为 processed 且 content_length > 0 但 chunks_count=0，属异常情况，应报 failed
