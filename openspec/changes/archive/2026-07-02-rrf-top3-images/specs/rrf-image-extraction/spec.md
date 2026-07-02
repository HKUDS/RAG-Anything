## ADDED Requirements

### Requirement: RRF 图片提取

系统 SHALL 在 RRF 检索完成后，从返回的 Top-N chunk 中提取图片路径，按 RRF 分数排序，取前 3 张不重复图片以 base64 编码返回。

#### Scenario: 基本图片提取
- **WHEN** RRF 检索返回 10 个 chunk，其中 3 个包含图片路径
- **THEN** 系统提取所有图片路径，按 chunk RRF 分数降序排列
- **THEN** 去重后取前 3 张，读取文件并 base64 编码
- **THEN** 返回 `{text, images: [{base64, path, source_chunk_id, rrf_score}]}`

#### Scenario: 无图片的 chunk
- **WHEN** RRF 检索返回的 chunk 中均不包含图片路径
- **THEN** 返回 `images: []` 空列表，不影响文本结果

#### Scenario: 图片文件不存在
- **WHEN** 提取到的图片路径对应的文件已被删除或不可读
- **THEN** 跳过该图片，继续处理下一张
- **THEN** 不抛出异常

### Requirement: 图片与文本同步返回

系统 SHALL 在 `_aquery_rrf` 中返回结构化结果，使调用方可以同时获取文本答案和相关图片。

#### Scenario: only_need_context 模式
- **WHEN** `_aquery_rrf` 在 `only_need_context=True` 下调用
- **THEN** 返回 `{text: <检索上下文>, images: <Top-3 base64 图片>}`

#### Scenario: 完整回答模式
- **WHEN** `_aquery_rrf` 在默认模式下调用
- **THEN** 返回 `{text: <LLM 生成的答案>, images: <Top-3 base64 图片>}`
