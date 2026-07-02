## Why

`query.py` 的 `/query`（非流式）和 `/query/stream`（流式）端点缺少实体图谱图片发现和 bigram 相关性评分，导致这两个端点的图片返回质量远低于 agent 端点——返回无相关性排序的全量图片，且丢失文本回填。这是三段式图片发现架构未统一应用到所有查询端点的功能缺口。

## What Changes

- 将 `_discover_images_via_graph()` 和 `_build_backfill_context()` 从 agent.py 提取到 shared.py，消除代码重复
- query_rag 端点添加图谱发现层 + bigram 评分兜底，替换当前的无评分全库扫描
- query_stream 端点同样添加三段式图片发现，替换当前的内存密集拼接扫描
- 统一图片返回上限为 3（与 agent 端点对齐）
- 为 query.py 端点添加文本回填，提升 VLM 回答质量

## Capabilities

### New Capabilities
- `query-endpoint-image-discovery`: `/query` 和 `/query/stream` 端点具备完整的实体图谱图片发现能力，与 agent 端点保持一致

### Modified Capabilities
- `graph-image-discovery`: 将图谱发现和回填构建函数提取为共享函数，供 agent.py 和 query.py 共同使用

## Impact

- `raganything/routers/shared.py` — 新增 `_discover_images_via_graph()` 和 `_build_backfill_context()` 共享函数
- `raganything/routers/agent.py` — 改为从 shared 导入，删除原地定义
- `raganything/routers/query.py` — query_rag 和 query_stream 路径添加三段式图片发现
