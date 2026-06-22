## Context

RAG-Anything 的文档处理管道分两阶段：文本提取（同步入库到 LightRAG）和多模态处理（VLM 描述图片/表格/公式 + 提取实体入图谱）。多模态处理由 `RAGAnythingConfig.enable_*_processing` 控制，默认值在 `config.py` dataclass 中定义为 `True`，但 `kb_service.py` 创建实例时用 `os.getenv(..., "false")` 硬编码覆盖为 `False`。

此外，`admin.py` 的设置 API 在多模态开关变更时不会清除已缓存的 KB 实例（`need_rebuild` 仅检查 `parser` 和 `entity_types`），导致开启开关后旧 KB 依然缺失多模态处理器。

用户核心诉求：**不重新上传、不删除原有文档**的情况下，让已入库的文档获得完整的多模态处理。

## Goals / Non-Goals

**Goals:**
- 统一 `kb_service.py` 与 `config.py` 的多模态默认值为 `true`（图片、表格、公式）
- 设置页切换多模态开关时，清除已缓存 KB 实例，使新配置生效
- 提供回溯处理 API：扫描 KB 中未完成多模态的文档，从原始文件（或解析缓存）恢复内容，仅执行多模态处理

**Non-Goals:**
- 不修改 `config.py` 的 dataclass 默认值（它已经是 `True`，是正确的）
- 不修改多模态处理器本身（`ImageModalProcessor` 等逻辑不变）
- 不修改前端（设置页 UI 已有开关，无需变更）
- 不处理 `enable_video_processing`（视频默认 `false` 是合理的，依赖 ffmpeg）

## Decisions

### Decision 1: 默认值统一到 `"true"`

**选择**: 修改 `kb_service.py:285-287`，将三个 `os.getenv(..., "false")` 的 fallback 改为 `"true"`。

**理由**: `config.py` dataclass 的 `field(default=get_env_value("ENABLE_IMAGE_PROCESSING", True, bool))` 已定义 `True`。`kb_service.py` 是唯一覆盖点，且覆盖值为 `"false"` 与 dataclass 矛盾。用户期望开箱即用支持图片/表格/公式。

**替代方案**: 删掉 `kb_service.py` 的显式传参，让 dataclass 默认值生效。但显式传参更可读，保留参数但改正默认值。

### Decision 2: 设置页变更时重建 KB 实例

**选择**: 在 `admin.py:update_settings` 中，当 `enable_image`/`enable_table`/`enable_equation`/`enable_video` 任一变更时，设置 `need_rebuild = True`，清除所有缓存的 KB 实例。

**理由**: 多模态处理器的注册发生在 `RAGAnything.__init__` 中（`raganything.py:227-246`），按 `config.enable_*` 条件注册。已创建的实例不会因后续 env var 变更而重新初始化，必须删除实例让下次访问时以新配置重建。

**替代方案**: 为 `RAGAnything` 添加动态注册/注销处理器的方法。但这增加了复杂度且处理器注册后 LightRAG 的内部状态难以回退。删除重建是最安全的方案。

### Decision 3: 回溯处理 — 重新解析 + 仅多模态

**选择**: 新增 `POST /api/kb/{kb_name}/reprocess-multimodal` 端点，流程如下：
1. 遍历 `kv_store_doc_status.json`，找 `multimodal_processed != true` 的文档
2. 对每个文档，从 `file_path` 定位原始文件（先在 `./uploads/` 下搜索，再尝试原路径）
3. 找到文件则调用 `parse_document()`（优先走解析缓存），提取 `content_list`
4. 用 `separate_content()` 分离出 `multimodal_items`
5. 调用 `_process_multimodal_content_background()` 在后台处理
6. 返回排队文档数

**理由**: 
- 复用了解析缓存：已解析过的文档直接从 `parse_cache`（KV 存储）读取，不需要重新跑 MinerU
- 不复用 doc_status 中已存的 content_list（doc_status 不存储完整 content_list，只存摘要）
- 后台处理不阻塞 HTTP 响应

**替代方案**: 直接访问 parse_cache KV 存储查找缓存条目。但缓存 key 是 `md5(file_path + mtime + config)`，难以反向查找。重新调用 `parse_document()` 最简单且会自动命中缓存。

### Decision 4: 原始文件定位策略

**选择**: 
1. 先尝试 doc_status 中的 `file_path` 是否为绝对路径且存在
2. 再搜索 `./uploads/` 目录（文件可能以随机前缀存储）
3. 都不存在：跳过该文档，返回 warning

**理由**: 上传文件存放在 `./uploads/{token}_{filename}`，原始 `file_path` 字段可能是 basename。搜索 uploads 目录能覆盖绝大多数场景。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| 回溯处理时原始文件已被删除 | 跳过并返回 warning，不影响其他文档 |
| 默认开启后，无 VLM 的部署场景（只有纯文本 LLM）会报错 | `ImageModalProcessor` 的 `modal_caption_func` 可回退到 `llm_model_func`；无视觉模型的场景会走文字描述路径 |
| 重建 KB 实例导致正在进行的查询中断 | 删除实例后下次访问才重建，当前进行中的查询已持有旧实例引用，不受影响 |
| 大量文档回溯处理可能导致 API 限流 | 后台逐个处理，由既有并发控制（`MULTIMODAL_MAX_CONCURRENT`）约束 |

## Open Questions

无——所有设计点已明确。
