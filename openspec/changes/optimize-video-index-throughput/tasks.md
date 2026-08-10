## 1. 配置与接线

- [x] 1.1 在 `RAGAnythingConfig` 新增 `video_segment_concurrent` 字段（`VIDEO_SEGMENT_CONCURRENT`，默认 2），并在 `__post_init__` 钳制到 [1, 4]（越界发 UserWarning）
- [x] 1.2 在 `raganything/raganything.py` 构造 `VideoModalProcessor` 时传入 `video_segment_concurrent=self.config.video_segment_concurrent`
- [x] 1.3 在 `.env.example` 声明 `VIDEO_SEGMENT_CONCURRENT`（带注释说明默认 2、上限 4、与 MAX_ASYNC 的关系）

## 2. 阶段耗时指标

- [x] 2.1 在 `raganything/video_processor/__init__.py` 增加毫秒计时辅助（perf_counter），覆盖探测、抽帧、ASR、场景检测阶段
- [x] 2.2 在 `_process_v2_segments` 记录每片段 describe/create/extract 耗时，输出 `video_v2_segment_metrics` 日志
- [x] 2.3 输出 `video_v2_metrics` 汇总日志（doc_id/segments/concurrent/total/probe/frames/asr/scene/describe/extract/pg），失败路径输出带 `failed=true` 的部分指标

## 3. 片段受控并发

- [x] 3.1 `VideoModalProcessor.__init__` 新增 `video_segment_concurrent` 参数（默认 2），创建 `self._segment_semaphore`
- [x] 3.2 将 `_process_v2_segments` 串行片段循环中的“描述+创建+抽取”抽为并发任务，受 `_segment_semaphore` 限制，用 `asyncio.gather` 执行并在首异常时取消其余
- [x] 3.3 并发任务返回 `(segment.index, chunk_id, chunk_results, visual_summary, frame_refs, local_text)`，存入按 index 归位的结果表；`pending_chunk_ids`/`pending_node_names` 继续登记供失败清理

## 4. 确定性写入顺序

- [x] 4.1 并发阶段结束后按 `segments` 原始顺序执行 `upsert_video_segment`（PG），并依序累积 `chunk_ids`、`chunk_results`、`segment_content_length`
- [x] 4.2 保持父节点与 `belongs_to` 边按 `chunk_ids` 顺序确定性生成；返回的 `entity_info["chunk_ids"]` 与 `chunk_results` 按片段序号升序

## 5. 延迟落盘

- [x] 5.1 `BaseModalProcessor._create_entity_and_chunk` 新增 `defer_flush: bool = False` 参数；`False`（默认）时行为不变，`True` 时跳过 `text_chunks_db.index_done_callback()`
- [x] 5.2 v2 片段调用 `_create_entity_and_chunk` 时传 `defer_flush=True`，最终落盘依赖调用方整文档 `_insert_done()`

## 6. 测试与验证

- [x] 6.1 配置测试：默认 2、环境变量覆盖、>4 钳制并警告、处理器缺省降级
- [x] 6.2 并发与顺序测试：多片段并发可观测（计时重叠/信号量上限）、PG 按序号写入、chunk_ids/chunk_results 升序、失败时取消其余并触发清理
- [x] 6.3 延迟落盘测试：v2 路径不调用逐块 `index_done_callback`，默认路径仍调用；指标日志断言（`video_v2_metrics`/`video_v2_segment_metrics`）
- [x] 6.4 回归：`tests/test_video_processor.py`、`tests/test_video_segments.py` 及相关视频测试通过；`py_compile`、`git diff --check`
- [x] 6.5 更新 `PROJECT_SUMMARY.md`（协调者执行）：记录视频索引吞吐优化落地与验证边界（真实 Worker/PG 时长收益待部署验收）
