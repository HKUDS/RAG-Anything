## ADDED Requirements

### Requirement: 阶段耗时指标

系统 SHALL 为每次 v2 视频索引记录各阶段耗时（毫秒），并以结构化日志输出，覆盖探测、抽帧、ASR、场景检测、VLM 描述、实体/块创建、实体抽取、PG 写入和总耗时。

#### Scenario: 成功索引时输出汇总指标

- **WHEN** 一个 v2 视频完成全部片段索引
- **THEN** 系统输出一条 `video_v2_metrics` 日志，包含 `doc_id`、`segments`、`concurrent`、`total_ms`、`probe_ms`、`frames_ms`、`asr_ms`、`scene_ms`、`describe_ms`、`extract_ms`、`pg_ms`
- **THEN** 各阶段耗时均为非负数值

#### Scenario: 输出逐片段明细指标

- **WHEN** 每个视频片段完成 VLM 描述与实体抽取
- **THEN** 系统输出 `video_v2_segment_metrics` 日志，包含 `doc_id`、`index`、`describe_ms`、`create_ms`、`extract_ms`

#### Scenario: 失败时输出部分指标

- **WHEN** v2 视频索引在完成前失败
- **THEN** 系统输出带 `failed=true` 的 `video_v2_metrics` 日志
- **THEN** 日志包含已执行阶段的耗时与失败前的片段数

### Requirement: 片段受控并发

系统 SHALL 在受控并发下并行处理同一视频中相互独立的语义片段，并发上限由 `video_segment_concurrent`（环境变量 `VIDEO_SEGMENT_CONCURRENT`）决定。

#### Scenario: 默认并发值

- **WHEN** 未设置 `VIDEO_SEGMENT_CONCURRENT`
- **THEN** `video_segment_concurrent` 默认值为 `2`
- **THEN** 处理器级信号量限制最多 2 个片段同时执行描述与实体抽取

#### Scenario: 并发上限钳制

- **WHEN** 设置 `VIDEO_SEGMENT_CONCURRENT` 大于 4
- **THEN** 配置值被钳制为 4 并发出 `UserWarning`
- **THEN** 处理器信号量上限为 4

#### Scenario: 片段并行不改变失败语义

- **WHEN** 任一片段处理失败
- **THEN** 其余片段任务被取消，整个视频任务失败并进入既有补偿清理
- **THEN** 不会留下部分成功片段或半成品 chunk/图谱产物

### Requirement: 确定性写入顺序

系统 SHALL 在并发处理后保持与串行路径一致的确定性写入顺序：PostgreSQL 片段行、chunk 列表和抽取结果均按片段序号排列。

#### Scenario: PG 片段行按序号写入

- **WHEN** 并发片段处理全部完成
- **THEN** `upsert_video_segment` 按 `segment.index` 升序调用
- **THEN** `video_segments` 行的 `segment_index` 与 `start_ms`/`end_ms` 与分段计划一致

#### Scenario: chunk 与抽取结果按序号返回

- **WHEN** `_process_v2_segments` 返回
- **THEN** `entity_info["chunk_ids"]` 按片段序号升序排列
- **THEN** `chunk_results` 按片段序号升序排列
- **THEN** 父节点和 `belongs_to` 边按 `chunk_ids` 顺序确定性生成

#### Scenario: 片段并发可观测

- **WHEN** 视频包含多个片段且 `video_segment_concurrent` 大于 1
- **THEN** 至少两个片段的 VLM 描述或实体抽取等待时间发生重叠（并发生效）

### Requirement: 延迟落盘

系统 SHALL 在 v2 视频路径跳过逐片段的 JSON 全量落盘，改由整文档完成后一次性持久化，同时保持既有幂等与失败清理语义。

#### Scenario: v2 片段不逐块落盘

- **WHEN** v2 视频处理片段并调用 `_create_entity_and_chunk`
- **THEN** 该调用不触发 `text_chunks_db.index_done_callback()`
- **THEN** 最终由调用方整文档 merge 后的 `_insert_done()` 一次性落盘

#### Scenario: 其他模态保持逐块落盘

- **WHEN** 非 v2 视频调用方调用 `_create_entity_and_chunk`
- **THEN** 行为与之前一致，每次创建后调用 `text_chunks_db.index_done_callback()`

#### Scenario: 失败清理不依赖落盘时机

- **WHEN** v2 视频失败
- **THEN** 补偿清理删除全部已登记 chunk/节点/向量
- **THEN** 重试前 `_preclean_v2_segment_artifacts` 可清除被杀进程遗留产物