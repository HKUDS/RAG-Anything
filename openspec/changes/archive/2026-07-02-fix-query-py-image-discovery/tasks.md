## 1. 共享函数提取

- [x] 1.1 将 `_discover_images_via_graph()` (agent.py:135-280) 移动到 shared.py，包括所需 import（asyncio, lightrag_logger, extract_image_paths, kb_dir, Path）
- [x] 1.2 将 `_build_backfill_context()` (agent.py:88-127) 移动到 shared.py
- [x] 1.3 在 shared.py `__all__` 中添加 `"_discover_images_via_graph"`, `"_build_backfill_context"`, `"_bigram_image_scan"`
- [x] 1.4 更新 agent.py：从 shared 导入 `_discover_images_via_graph` 和 `_bigram_image_scan`，删除原地定义
- [x] 1.5 额外提取 `_bigram_image_scan()` 到 shared.py，消除 agent.py 内 Normal RAG 和 AgenticRAG 路径的重复代码

## 2. query_rag 端点修复

- [x] 2.1 在 query_rag 中调用 `shared._discover_images_via_graph()` 替换无评分全库扫描（query.py:199-217）
- [x] 2.2 添加 bigram 评分兜底（通过 `shared._bigram_image_scan()`）
- [x] 2.3 添加回填文本注入 ctx（图谱回填 + bigram 回填）
- [x] 2.4 将图片上限统一为 3（`vlm_images = ctx_images[:3]`，与 agent 端点对齐）

## 3. query_stream 端点修复

- [x] 3.1 将 query_stream 的内存拼接全库扫描替换为三段式发现（query.py:490-505）
- [x] 3.2 移除 `'\n'.join(all_content_values)` 的大字符串拼接
- [x] 3.3 添加 bigram 评分兜底（通过 `shared._bigram_image_scan()`）
- [x] 3.4 将图片上限统一为 3（`stream_images = stream_images[:3]`）

## 4. 验证

- [x] 4.1 语法检查：确认 shared.py、agent.py、query.py 无语法错误
- [x] 4.2 导入检查：确认 `_discover_images_via_graph`、`_build_backfill_context`、`_bigram_image_scan` 可从 shared 导入
- [x] 4.3 数据流验证：`_build_backfill_context` 和 `extract_image_paths` 函数正确性测试通过
- [x] 4.4 集成追踪：4 条代码路径均调用相同的共享函数，图片上限统一为 [:3]
