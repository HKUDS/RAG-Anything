# BM25 Keyword Index (Delta)

## MODIFIED Requirements

### Requirement: BM25 score threshold
BM25 通道 SHALL 不过滤负分或零分结果。所有 BM25 打分结果按其相对排序参与 RRF rank-based fusion。

#### Scenario: Small corpus with negative BM25 scores
- **WHEN** 语料库文档数 ≤ 10 且查询词出现在多篇文档中导致 BM25 IDF 为负
- **THEN** BM25 通道 SHALL 依然返回排序后的结果列表，不因分数 ≤ 0 而丢弃

#### Scenario: Large corpus with positive scores
- **WHEN** 语料库文档数 > 100 且查询词有良好区分度
- **THEN** BM25 通道 SHALL 正常返回正分排序结果，行为与修复前一致

## REMOVED Requirements

### Requirement: Filter BM25 scores <= 0
**Reason**: 小语料库下 BM25 IDF 公式产生负值是正常数学行为，rank-based RRF 融合不依赖绝对分数大小。过滤 `<= 0` 导致 BM25 通道在小 KB 中完全失效。
**Migration**: 直接移除 `if scores[idx] <= 0: continue` 行。
