## Why

v2 语义分段已产出高质量中文分段和标签，但长视频的实体抽取按片段串行执行，单个片段常耗时 30–55 秒（实体抽取 LLM 调用是主要瓶颈）；同时每个片段写入都会完整重写 JSON 存储文件，片段越多写入开销呈二次方增长。用户上传长视频的索引吞吐不足。

## What Changes

- 为 v2 视频索引新增各阶段耗时指标：探测、抽帧、ASR、场景检测、VLM 描述、实体抽取、PG 写入与总耗时，按视频和按片段输出结构化日志。
- 在受控并发下并行处理相互独立的语义片段（新增 `VIDEO_SEGMENT_CONCURRENT`，默认 2、上限 4），重叠 VLM 描述与实体抽取的等待时间，同时避免打爆模型调用并发。
- 保持确定性写入顺序：并发结果按 `segment.index` 归位，PostgreSQL `video_segments` 行按片段序号顺序写入，`chunk_ids`/`chunk_results` 以片段顺序返回，父节点与 `belongs_to` 边仍按序号确定性生成。
- 消除 v2 路径逐片段 JSON 全量落盘：片段写入阶段延迟 flush，最终由调用方已有的整文档 `merge_nodes_and_edges` + `_insert_done()` 一次性落盘，幂等与失败清理语义不变。
- 配置与文档同步：`RAGAnythingConfig` 新增 `video_segment_concurrent`（含钳制校验）、处理器构造与 `.env.example` 声明。

## Capabilities

### New Capabilities

- `video-index-throughput`: v2 视频分段的阶段耗时指标、受控并发处理和确定性写入顺序的契约。

### Modified Capabilities

- `video-config-integration`: 新增 `VIDEO_SEGMENT_CONCURRENT` 配置项及其默认值/钳制行为，并透传到 `VideoModalProcessor`。
- `video-knowledge-graph`: 视频片段实体抽取从逐片段串行改为受控并行，最终图谱合并保持整文档一次完成、结果确定。

## Impact

- `raganything/config.py`、`raganything/raganything.py`：新增并发配置与接线。
- `raganything/video_processor/__init__.py`：`_process_v2_segments` 并行化、阶段计时与延迟 flush。
- `raganything/modalprocessors/base.py`：`_create_entity_and_chunk` 支持可选延迟 flush（默认行为不变，不影响图片/表格等其他模态）。
- `.env.example`：声明新环境变量。
- 测试：`tests/test_video_processor.py` 及新增计时/并发/顺序单元测试；不改数据库迁移、任务状态接口或上传快照字段。
