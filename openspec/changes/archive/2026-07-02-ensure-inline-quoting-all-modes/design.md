## Context

当前问题：LightRAG 原生模式（hybrid/mix/local/global/naive）的 `aquery()` 返回纯文本 context，格式由 LightRAG 内部控制。当查询返回图谱实体时（`0 chunks, 37 entities, 44 relations`），context 中只有实体名和描述，没有文档名。LLM 看到 `INLINE_QUOTE_INSTRUCTION` 要求标注 `（来源：文档名）`，但没有文档名可用，于是用实体名凑：`（来源实体："xxx"）`。

## Goals / Non-Goals

**Goals:**
- LightRAG 原生模式也能输出 `"原文..."（来源：文档名）` 格式
- 不修改 LightRAG 内部源码
- 利用已有的 `_chunk_source_cache` 数据

**Non-Goals:**
- 不改变 LightRAG 的检索逻辑
- 不修改 LightRAG 的 context 格式

## Decisions

### Decision 1: 在 server.py 层注入文档信息

在 `server.py` 构建 `final_prompt` 之前，从 LightRAG context 中提取可知文档信息，在 prompt 中追加文档列表。

```python
# 伪代码
# 1. 列出 KB 中所有已知文档（从 doc_status cache）
docs_list = await get_available_docs(kb)
# 2. 在检索内容前注入文档参考列表
doc_hint = "\n".join(f"- {d['name']} ({d['file_path']})" for d in docs_list)
ctx_with_hint = f"## 可用文档列表\n{doc_hint}\n\n## 检索内容\n{ctx}"
```

**理由**：最简单直接，不侵入 LightRAG。LLM 有了文档名列表后，自然会选择正确的文档名标注来源。

### Decision 2: 优先使用 RRF 模式

对于需要精确来源引用的场景，建议智能体默认使用 RRF 模式（已有完整文档名支持）。LightRAG 原生模式作为补充兼容。

### Decision 3: 降级策略

如果 context 中完全没有文档名信息（KB 无文档或全是外部数据），LLM 按最新指令"只引原文，不编造来源"即可。

## Risks / Trade-offs

- **[风险] LLM 可能选错文档名** → 文档列表 + context 内容交叉验证
- **[权衡] 文档列表增加 token 消耗** → 仅列出前 10 个文档，约 200 tokens
