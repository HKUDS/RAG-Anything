## 1. 配置层：新增环境变量透传

- [x] 1.1 在 `.env` 中新增 `EMBEDDING_BATCH_SIZE=20` 和 `ENTITY_EXTRACT_CONCURRENCY=3` 环境变量
- [x] 1.2 在 `raganything/config.py` 中新增 `embedding_batch_size` 和 `entity_extract_concurrency` 配置字段
- [x] 1.3 在 `server.py` 的 `create_rag()` 中将 `embedding_func_max_async` 参数映射到 LightRAG kwargs

## 2. 核心优化：Embedding 批量调用

- [x] 2.1 修改 `process_worker.py` 的 `create_rag()`，将 embedding_func 改为支持批量模式（一次接收 `list[str]`，返回 `list[list[float]]`）
- [x] 2.2 修改 `raganything/processor.py` 的 `_store_chunks_to_lightrag_storage_type_aware`：收集 chunk 文本后批量调用 embedding API，再分别写入 vdb
- [x] 2.3 将 `Semaphore(10)` 调整为 `Semaphore(EMBEDDING_BATCH_SIZE)`，以 batch 为粒度控制并发
- [x] 2.4 添加批量 embedding 失败时的逐条重试降级逻辑

## 3. 核心优化：LightRAG 参数调优

- [x] 3.1 在 `process_worker.py` 的 `lightrag_kwargs` 中传入 `embedding_func_max_async`（值来自 `ENTITY_EXTRACT_CONCURRENCY`）
- [x] 3.2 在 `server.py` 的 `create_rag()` 中同步传入 `embedding_func_max_async` 参数
- [x] 3.3 验证 LightRAG 版本是否接受 `embedding_func_max_async` 参数；如不支持则使用环境变量注入

## 4. 进度细化：分阶段上报

- [x] 4.1 在 `process_worker.py` 的关键步骤之间插入 `emit_progress` 调用，输出结构化进度行：`parsing(N/M)` → `chunking(N/M)` → `entity-extraction(N/M)` → `embedding(N/M)` → `graph-building`
- [x] 4.2 修改 `server.py` 的 worker stdout 解析逻辑，识别 `[PROGRESS] phase=... current=... total=...` 格式并更新 `processing_tasks`
- [x] 4.3 前端 `KnowledgePage.jsx` 中展示当前处理阶段文字标签

## 5. Prompt 精简

- [x] 5.1 审查 `raganything/prompts_zh.py` 中实体抽取相关 prompt（`table_prompt`、`generic_prompt`），移除冗余描述，目标减少 20-30% token
- [x] 5.2 对 `raganything/prompt.py` 的英文 prompt 做同步精简

## 6. 验证与测试

- [ ] 6.1 对同一文档（7.毕业设计论文.docx）用新配置重新处理，对比处理耗时（目标：总时间 ≤ 25 分钟）
- [ ] 6.2 验证批量 embedding 结果与原单条模式结果一致（向量相似度 ≥ 0.99）
- [ ] 6.3 验证处理完成后查询质量不下降（同"毕业答辩的地点"等查询对比答案正确性）
- [ ] 6.4 验证批量 embedding 失败降级逻辑（可通过临时设置无效 API key 测试）
