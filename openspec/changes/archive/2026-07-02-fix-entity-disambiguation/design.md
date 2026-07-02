## Context

当前图谱实体匹配 (`graph_rag.py:98-141`) 使用纯子串匹配：`entity_name.lower() in query.lower()`。当文档包含"开题答辩"和"毕业设计答辩"时，查询"毕业设计答辩地点"中的"答辩"子串同时命中两者。匹配结果按实体 graph degree 排序，而非按匹配特定度排序。这导致更通用的实体（度更高）排名更靠前，但更特定（更相关）的实体被淹没。

后续 BFS 遍历从所有匹配实体收集 chunk，混合了不同实体的属性数据。LLM 收到未标注实体来源的混合上下文，无法区分 13220 属于"开题答辩"、13216 属于"毕业设计答辩"。

## Goals / Non-Goals

**Goals:**
- 图谱检索优先匹配与查询最相关的实体（token 重叠度更高的实体排名更高）
- 检索上下文携带实体来源信息，使 LLM 能将事实与正确实体关联
- LLM 提示词包含实体区分指导

**Non-Goals:**
- 不改变向量检索和 BM25 检索通道的行为
- 不引入新的嵌入模型或外部消歧服务
- 不修改 LightRAG 底层实体抽取逻辑
- 不改变 RRF 融合算法本身

## Decisions

### 决策 1: Token 重叠度匹配算法

**选择**: 使用 jieba 分词后的集合交集大小作为匹配分数

**算法**:
```python
query_tokens = set(jieba.lcut(query))
for entity_name in all_entity_names:
    entity_tokens = set(jieba.lcut(entity_name))
    overlap = len(query_tokens & entity_tokens)
    if overlap > 0:
        score = overlap
```

**排序**: 先按 score 降序，同分按 graph degree 降序

**理由**:
- "毕业设计答辩" vs 查询 "毕业设计答辩地点"：jieba 分词后重叠 tokens = {"毕业设计", "答辩"} → score=2
- "开题答辩" vs 同一查询：jieba 分词后重叠 = {"答辩"} → score=1
- "毕业设计答辩" 得分更高，优先遍历，其关联的 chunk 包含 13216

**替代方案**:
- 方案 B: 使用向量相似度匹配 → 需要额外 embedding 调用，增加延迟，过度工程化
- 方案 C: 在 LLM prompt 层面解决（不改检索）→ 不解决根本问题，LLM 仍收到混合上下文
- 方案 D: 使用最长公共子串 (LCS) → "毕业设计答辩" 和查询的 LCS 为 "答辩"（4字）vs "开题答辩" 的 LCS 为 "答辩"（2字），但对中文分词不如 jieba 语义准确

### 决策 2: 实体来源标注格式

**选择**: 在 chunk 文本前添加 `[来源实体: {entity_name}]` 前缀

**数据传递路径**: `_traverse_neighbors()` 已记录 `chunk_id → entity_path` 映射。需要修改返回值结构，将 `entity_name` 随 chunk 一起传递到 `_aquery_rrf()` 的上下文构建阶段。

**理由**: 在 chunk 文本前加前缀是最低侵入性的方式 —— 不改变 chunk 数据结构，不影响向量/BM25 通道，只改变传给 LLM 的文本表示。LLM 原生理解自然语言标注。

**替代方案**:
- 方案 B: 在 prompt 的元数据区列出实体-chunk 映射表 → LLM 需要额外推理步骤来查表
- 方案 C: 修改 chunk 数据结构增加 `source_entities` 字段 → 改变序列化格式，影响缓存

### 决策 3: 提示词增强内容

**选择**: 在 RAG 查询提示的"要求"部分增加一行实体消歧指令

原文（server.py:2244）:
```
从检索内容提取事实和数据。结合对话历史理解上下文。有数字必须引用。没有就说未找到。不编造。
```

新增:
```
从检索内容提取事实和数据。结合对话历史理解上下文。有数字必须引用。没有就说未找到。不编造。如果检索内容包含多个名称相似的实体（如"开题答辩"和"毕业设计答辩"），必须严格区分各实体对应的属性值，不得混淆。
```

**理由**: 一行指令即可显著改善 LLM 行为。不需要改变 prompt 结构或增加 token 开销。

## Risks / Trade-offs

- **[风险] jieba 分词可能对专业术语分词不准**: 如"毕业设计答辩"可能被切为 ["毕业", "设计", "答辩"] 而非 ["毕业设计", "答辩"] → **缓解**: 同时使用原始子串匹配作为 fallback（保留原逻辑），token 重叠仅用于排序加权
- **[风险] 实体来源标注增加上下文长度**: 长文档可能涉及数十个实体 → **缓解**: 仅对图谱通道结果标注（通常 < 10 个 chunk），不影响向量和 BM25 通道
- **[权衡] 两个相似度相同的实体（如查询"答辩"）不分先后**: 无法在这种查询下区分 → **接受**: 查询本身不够具体时，两个实体都相关是合理的。此时依赖 chunk 来源标注让 LLM 自行判断

## Migration Plan

1. 修改 `graph_rag.py` 的 `_match_entities()` 和 `_traverse_neighbors()` 返回值
2. 修改 `query.py` 的 `_aquery_rrf()` 上下文构建逻辑
3. 修改 `server.py` 的 RAG 提示词
4. 无需数据迁移，无需 API 变更
5. 回滚: git revert，无破坏性变更
