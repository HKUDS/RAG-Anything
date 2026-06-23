## Context

当前 `query.py` 的图片发现仅有二级：直接提取 + 全库 dump（无评分）。agent.py 已有完整的三级发现：直接提取 → 图谱发现 → bigram 评分兜底。`_discover_images_via_graph()` 和 `_build_backfill_context()` 是两个独立于 agent 逻辑的纯函数，适合提取到 shared.py 供多处复用。

## Goals / Non-Goals

**Goals:**
- query.py 的 `/query` 和 `/query/stream` 端点具备与 agent 端点同等的图片发现能力
- 消除 shared.py / agent.py 之间的代码重复
- 统一图片返回上限为 3

**Non-Goals:**
- 不改变图谱发现或 bigram 评分的核心算法
- 不重构 query.py 的其他不相关逻辑
- 不修改 agent.py 的图片发现行为（仅改变导入来源）

## Decisions

### D1: 将共享函数提取到 shared.py（而非新建模块）

**选择**: 追加到 `shared.py`
**理由**:
- `extract_image_paths()` 已在 shared.py，三者天然属于同一层（图片发现工具函数）
- shared.py 是 router 层的共享入口，query.py 已通过 `shared.xxx` 访问
- 避免新增模块增加认知负担
**备选**: 新建 `raganything/utils/image_discovery.py` — 更干净但引入额外导入路径，对本改动过大

### D2: query.py 中优先使用图谱发现，fallback 用 bigram 评分扫描

**选择**: 三段式：直接提取 → 图谱发现 → bigram 兜底
**理由**: 与 agent.py 对齐，确保所有端点行为一致
**备选**: 仅添加图谱发现不添加 bigram — 但 agent.py 已有 bigram，不如全对齐

### D3: 不修改 query_rag 的 VLM 增强路径结构

**选择**: 保留现有 `vlm_images` → `instance.aquery_vlm_enhanced()` 调用路径，仅改变 `ctx_images` 的获取方式
**理由**: VLM 增强是 query_rag 的特有逻辑，不在本次修复范围

### D4: query_stream 中代替字符串拼接的全库扫描

**选择**: 用与 agent.py 相同的逐 chunk 遍历替代 `'\n'.join(all_contents)`
**理由**: 逐 chunk 遍历内存友好、支持 bigram 评分、可去重

## Risks / Trade-offs

- [风险] query.py 新增图谱调用增加 0-8s 延迟（图谱查询超时）→ 缓解：与 agent.py 已有的超时和重试机制一致
- [风险] `_discover_images_via_graph()` 内部使用 `kb_dir()` 依赖 `.env` → 缓解：shared.py 已有 `load_dotenv`，环境一致
- [回滚] 如发现问题，恢复 query.py 原有的简单全库扫描即可，改动集中
