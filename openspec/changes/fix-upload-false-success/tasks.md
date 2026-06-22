## 1. Worker 进程失败检测修正

- [x] 1.1 修改 `process_worker.py` 中后处理验证条件：将 `if info.get("chunks_count", 0) == 0 and not info.get("status") == "failed":` 改为 `if info.get("chunks_count", 0) == 0 or info.get("status") == "failed":`

## 2. 主进程后处理数据验证

- [x] 2.1 在 `raganything/services/kb_service.py` 的 `_process_uploaded_file` 中，worker 成功返回后读取 `kv_store_doc_status.json`，根据文件名匹配对应条目，验证 `chunks_count > 0`，否则将任务标记为 `failed`

## 3. process_document_complete 添加 _insert_done

- [x] 3.1 在 `raganything/processor/doc_processor.py` 的 `process_document_complete` 方法中，`insert_text_content` 返回后、status 更新前，添加 `await self.lightrag._insert_done()` 调用

## 4. finalize_storages 异常日志

- [x] 4.1 修改 `raganything/services/kb_service.py` 中 `finalize_storages()` 的 `except Exception: pass` 为 `except Exception as e:` 并记录 warning 日志
