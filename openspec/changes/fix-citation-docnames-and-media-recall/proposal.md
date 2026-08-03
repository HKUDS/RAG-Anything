## Why

知识库问答的引用来源在服务重启后退化为“未知文档-chunk-xxxx”，因为 chunk→文档名映射只存在于进程内内存缓存，PG 部署下无法从持久化数据重建；同时，由项目自有解析产物（`output_*` 目录）生成的图片块无法通过受控媒体校验，导致回答中缺失引用图片。

## What Changes

- 将 `_ensure_chunk_source_cache` 的重建逻辑扩展为：检测到 PG 存储（`getattr(doc_status_store, "db", None) is not None`）时，直接通过 `doc_status_store.db` 按 `doc_status_store.workspace` 查询 `LIGHTRAG_DOC_STATUS` 的 `file_path` 与 `chunks_list` 重建 chunk→文档名映射（文档名经 `_get_file_reference` 生成，与处理期注册一致）；JSON 存储保留原 `_data` 内存路径。
- 重建结果使用 60 秒 TTL 刷新并加实例级锁，避免一次性构建导致新上传文档的引用仍退化为“未知文档”；单行坏数据不中断整批重建；失败不标记成功以便重试。
- 将项目自有解析输出目录纳入受控媒体根：项目根下精确匹配 `output` 与 `output_*` 目录、以及调用时读取的 `OUTPUT_DIR` 环境变量目录（相对路径按项目根绝对化），使召回校验、legacy 媒体 grant 签发与 `/api/knowledge/media/legacy/{grant}` 服务端一致放行。交付仍要求图片后缀、真实文件、KB 绑定 grant 及“路径出现在该 KB 持久化 chunk 内容中”的证据链。
- 为可测试性，将项目根提取为模块级 `_project_root()` 辅助函数；`_controlled_roots()` 增加短 TTL 进程级缓存与测试重置钩子。
- 不改动前端、三段式图片召回与“至少保留 1 张”兜底逻辑、媒体召回时间预算；`odl解析` 知识库无图片块属解析产物问题，按运维项处理（重新解析），本次不写代码。

## Capabilities

### New Capabilities
<!-- 无新能力 -->

### Modified Capabilities
- `citation-source-tracing`: 源文档追溯映射在 PG 存储下必须从持久化数据重建且定期刷新，服务重启或新文档上传后引用不再退化为“未知文档”。
- `query-endpoint-image-discovery`: 受控媒体根必须包含项目自有解析输出目录（`output`/`output_*`/`OUTPUT_DIR`），使这些目录下的图片块可通过证据链召回与交付；项目外路径仍拒绝。说明：该能力作为图片召回与交付的总纲；`add-opendataloader-pdf-parser` 变更中 `opendataloader-pdf-ingestion` 的“统一受控媒体校验器”需求保持单一校验器不变，仅受控根集合扩大。

## Impact

- 后端代码：`raganything/processor/chunk_processor.py`（缓存重建）、`raganything/services/odl_media_delivery.py`（受控根与项目根辅助函数）。
- 测试：`tests/test_query_image_recall.py`、`tests/test_query_execution_deadline.py`、`tests/testodl_media_delivery.py` 及新增用例（PG 重建三态解析/失败重试/TTL、JSON 回归、受控根集合）。
- 无 API、数据库迁移或前端改动。
- 安全模型：受控根扩大后，攻击面为“已认证用户在自己 KB 的 chunk 内容中写入已知绝对路径即可经 grant 读取该路径图片”；该模型与既有 `odl-artifacts` 一致，交付仍受同 KB 证据、KB 绑定 grant、sha256 与 TTL 约束。跨 KB 引用、无证据路径均无法交付。
- 收尾任务包含 `PROJECT_SUMMARY.md` 同步与近期任务复盘记录（AGENTS.md 强制）。
