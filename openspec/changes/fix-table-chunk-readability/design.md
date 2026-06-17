## Context

表格 chunk 模板 (`prompt.py:426-432`) 当前顺序：
```
Table Analysis:
Image Path: ...
Caption: ...
Structure: {bbox...}     ← 巨大的 JSON，可能数千字符
Footnotes: ...
Analysis: {description}  ← LLM 可读描述，被埋在末尾
```

问题：`Structure` 包含所有单元格的完整 bbox 坐标（每个 cell 约 200+ 字符），一张 20 单元格的表就有 4000+ 字符的裸数据。`Analysis` 在末尾，LLM 可能因注意力衰减或截断而忽略。

## Goals / Non-Goals

**Goals:**
- 表格 chunk 中 LLM 可读的 `Analysis` 描述优先于原始数据
- 减少 `Structure` 的体积，保留表格逻辑结构

**Non-Goals:**
- 不改动 LLM 表格分析的质量
- 不影响图片、公式等其他模态的 chunk 模板
- 不修改 LightRAG 的 chunk 存储逻辑

## Decisions

### 决策 1: 模板重排 — Analysis 提到 Structure 前面

**选择**: 调整模板为：
```
Table Analysis:
Caption: ...
Analysis: {enhanced_caption}
Structure: {simplified_structure}
Footnotes: ...
```

**理由**: 最简单、最直接的修复。LLM 第一时间看到 Analysis 描述。只需修改模板字符串。

### 决策 2: Structure 简化

**选择**: 在 `_apply_chunk_template()` 的 table 分支中，对 `table_body` 预处理——从每个 cell 中只提取 `{text, row, col}` 三条信息，去掉 bbox、header flags、fillable 等。

**转换逻辑**:
```python
simplified_cells = []
for i, cell in enumerate(table_cells):
    simplified_cells.append({
        "row": i,  # position index instead of bbox
        "text": cell.get("text", "")
    })
```

**理由**: bbox 坐标对 LLM 阅读理解无意义。保留文字和顺序足够 LLM 理解表格结构。

### 决策 3: 长表格截断

**选择**: 简化后的 Structure 若仍超过 2000 字符，截断并标注 `（表格数据过长，已截断，完整分析请见上方 Analysis）`

**理由**: 防止超大表格仍然撑爆 chunk。

## Risks / Trade-offs

- **[风险] bbox 坐标可能用于表格渲染/前端展示**: → **缓解**: 原始数据仍在 `original_item` 中，仅在 chunk 文本表示中简化
- **[权衡] 简化丢失精确列对齐信息**: → **接受**: `row`/`col` 索引足以理解行列关系，LLM 不需要像素级坐标
