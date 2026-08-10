## Context

v2 视频语义分段流程位于 `raganything/video_processor/__init__.py::_process_v2_segments`（约 1221 行起）。当前对每个片段串行执行：

1. `_describe_segment_frames`：最多 3 帧 VLM 分析 + 1 次片段综合（帧级已有 `video_frame_concurrent` 信号量，默认 3）。
2. `_create_entity_and_chunk`：写 text_chunks 并逐片段 `index_done_callback()` 全量重写 JSON、写 chunks_vdb、图谱节点、实体向量，然后 `_process_chunk_for_extraction` 执行 `extract_entities`（实体抽取 + gleaning 共 2 次 LLM 调用/片段，是 30–55 秒的主瓶颈；batch 模式下不做 merge）。
3. `upsert_video_segment` 写入 PostgreSQL。

调用方 `multimodal_processor._process_multimodal_content_individual` 在全部片段完成后，已统一执行一次整文档 `merge_nodes_and_edges` + `_insert_done()`。因此片段之间无数据依赖：描述、实体抽取、chunk 写入均可并行；最终图谱合并本就是一整文档一次，天然确定。

## Goals / Non-Goals

**Goals:**

- 加各阶段耗时指标：探测、抽帧、ASR、场景检测、VLM 描述、实体/块创建、实体抽取、PG 写入与总耗时；按视频一条汇总 + 按片段一条明细，结构化 key=value 便于日志检索。
- 受控并发处理独立片段：`VIDEO_SEGMENT_CONCURRENT` 默认 2、上限 4，通过处理器级 `asyncio.Semaphore` 限定，重叠 VLM 描述与实体抽取等待。
- 确定性写入顺序：并发结果按 `segment.index` 归位；PG `upsert_video_segment`、`chunk_ids`、`chunk_results` 均按片段序号顺序输出；父节点与 `belongs_to` 边保持确定性。
- 消除逐片段 JSON 全量落盘：`_create_entity_and_chunk` 新增可选 `defer_flush`，v2 路径跳过逐片段 `index_done_callback()`，最终由调用方已有的整文档 `_insert_done()` 一次性落盘。

**Non-Goals:**

- 不改数据库迁移、上传快照、任务状态接口或 `video_segments`/`video_assets` 表结构。
- 不修改 `extract_entities`/`merge_nodes_and_edges`（vendored LightRAG）内部实现；并发只发生在本项目编排层。
- 不改变失败语义：任一片段失败仍整体失败、补偿清理、可重试；不引入部分成功。
- 不并行不同文档的写入（Worker 进程模型不变）。

## Decisions

### 1. 阶段计时：处理器内收集、结构化日志输出

在 `_process_v2_segments` 内用 `time.perf_counter()` 记录各阶段耗时（毫秒），收集到 `dict[str, float]`；每片段记录 describe/create/extract 明细。结束时输出：

- `video_v2_metrics doc_id=<id> segments=<n> concurrent=<c> total_ms=<t> probe_ms=<p> frames_ms=<f> asr_ms=<a> scene_ms=<s> describe_ms=<d> extract_ms=<e> pg_ms=<g>`
- 每片段 `video_v2_segment_metrics doc_id=<id> index=<i> describe_ms=<d> create_ms=<c> extract_ms=<e>`

失败路径也输出部分指标并带 `failed=true`，便于监控定位长尾片段与失败阶段。

理由：最小侵入、无需新依赖；key=value 便于 `Select-String`/日志平台解析。备选：写 `doc_status.metadata`——会改变文档元数据结构且重试时需合并，否决。

### 2. 片段级受控并发：处理器级信号量 + `asyncio.gather`

- `VideoModalProcessor.__init__` 新增 `video_segment_concurrent: int = 2`，创建 `self._segment_semaphore = asyncio.Semaphore(video_segment_concurrent)`。
- `_process_v2_segments` 中把串行 `for offset, segment in enumerate(segments)` 的“描述+创建+抽取”部分抽为 `_process_one_segment(offset, segment)`，内部 `async with self._segment_semaphore`，返回按 `segment.index` 索引的结果。
- 用 `asyncio.gather(*(...))` 并发执行；首个异常按 gather 默认语义取消其余任务并上抛，外层既有 `except` 补偿清理不变。

并发上限依据：`extract_entities` 内部信号量为 `llm_model_max_async`（`MAX_ASYNC`，默认 4）；并行 P 个片段时最坏抽取 LLM 并发 = P × 4，另有至多 P×3 帧 VLM 调用。默认 P=2 即最坏 8 条抽取并发，配合 MAX_ASYNC 可调，属可控范围。

备选：全局共享抽取信号量——需要 fork vendored LightRAG，否决；按片段直接无界 gather——会打爆模型端点，否决。

### 3. 确定性写入顺序：结果归位 + 序号遍历

- 并行阶段只做计算与内存写入（text_chunks/chunks_vdb/图谱节点/实体向量/实体抽取），并把 `(segment.index, chunk_id, chunk_results, visual_summary, frame_refs, local_text)` 存入 `results_by_index[segment.index]`。
- 并行阶段结束后，按 `segments` 原始顺序遍历：`upsert_video_segment`（PG）、`chunk_ids.append`、`results.extend`、`segment_content_length` 累加，保证对外可观测顺序与之前完全一致。
- 父节点与 `belongs_to` 边循环不变（按 `chunk_ids` 顺序）。
- `pending_chunk_ids`/`pending_node_names` 在并发任务内追加用于失败清理；追加顺序不影响清理正确性（asyncio 单线程，list.append 安全）。

理由：PG 行与 chunk 列表顺序是既有契约（`chunk_order_index = chunk_order_index + segment.index` 本身确定），并发完成顺序不应影响最终数据；归位后写可严格保持。

### 4. 延迟 flush：`defer_flush` 可选参数

- `BaseModalProcessor._create_entity_and_chunk` 新增 `defer_flush: bool = False`；仅当 `False`（默认，兼容图片/表格/方程等既有调用）时调用 `self.text_chunks_db.index_done_callback()`。
- v2 调用传 `defer_flush=True`，消除逐片段全量 JSON 重写（O(n²) 写放大）。
- 最终落盘由调用方 `_process_multimodal_content_individual` 在整文档 merge 后已有的 `await self.lightrag._insert_done()` 完成；`_process_chunk_for_extraction` 从内存 `text_chunks_db` 读回 chunk（存储锁保护），不受延迟 flush 影响。
- 失败时补偿清理直接删除存储中的 chunk 记录；内存与磁盘状态在下次 `_insert_done()` 前保持一致，`_preclean_v2_segment_artifacts` 兜底清理遗留。

理由：v2 视频是原子索引单元（已有补偿清理），逐片段落盘没有崩溃安全价值，只有写放大成本。备选：批量分 N 次 flush——仍非必要，否决。

### 5. 配置接线

- `RAGAnythingConfig` 新增 `video_segment_concurrent: int = get_env_value("VIDEO_SEGMENT_CONCURRENT", 2, int)`，`__post_init__` 钳制到 `[1, 4]`（越界发 UserWarning）。
- `raganything.py` 构造 `VideoModalProcessor` 时传入 `video_segment_concurrent=self.config.video_segment_concurrent`。
- `.env.example` 增加注释声明。

## Risks / Trade-offs

- **有效 LLM 并发翻倍**：并行片段 × `extract_entities` 内部 `MAX_ASYNC` 可能触发模型端点限流 → 默认并发取 2，文档说明与 `MAX_ASYNC` 的耦合；若限流可调低 `VIDEO_SEGMENT_CONCURRENT` 或 `MAX_ASYNC`。
- **并发内存写入竞争**：多片段同时 upsert 共享 JsonKVStorage/图谱存储 → 各存储已有命名空间锁保护；写入键确定性互不冲突；失败时补偿清理按 chunk_id 删除，不依赖写入顺序。
- **`index_done_callback` 延迟后崩溃窗口**：延迟 flush 使成功路径落盘推迟到整文档 merge 后 → v2 原子语义 + 补偿清理保证失败不留半成品；`_preclean_v2_segment_artifacts` 兜底被杀进程遗留。
- **gather 取消时序**：首个异常触发其余任务取消，可能在半途写入 → 外层 `except` 的补偿清理会删除全部 `pending_chunk_ids`/`pending_node_names`，与现有串行失败路径一致。
- **计时开销**：perf_counter + 日志，毫秒级，可忽略。

## Migration Plan

1. 代码随常规发布部署；无数据库迁移、无公共 API 字段变更。
2. 旧 Worker 不识别新配置时回退默认 2（进程内信号量，无持久状态）。
3. 回滚：还原代码即可；存量视频数据与正在处理任务不受影响（快照字段未变）。
4. 部署后以一个真实 MP4 验证：日志出现 `video_v2_metrics`，PG 行顺序与分段一致，检索命中中文分段，失败任务仍可重试。
