## ADDED Requirements

### Requirement: ScoredChunk 包含源文档追溯字段

`ScoredChunk` 数据结构 SHALL 包含 `file_path`、`document_name`、`chunk_index` 三个可选字段，使每个检索命中的文本块能追溯到其源文档。

#### Scenario: RRF 查询模式下 chunk 携带源信息

- **WHEN** 系统通过 RRF 混合检索模式执行查询
- **THEN** 每个 `ScoredChunk` 的 `file_path` 字段 MUST 包含源文件的完整路径
- **AND** `document_name` 字段 MUST 包含可显示的文档名称（文件名或用户配置的路径格式）
- **AND** `chunk_index` 字段 MUST 包含该 chunk 在源文档内的序号

#### Scenario: Graph 查询模式下 chunk 携带源信息

- **WHEN** 系统通过知识图谱查询模式执行查询
- **THEN** 每个 `ScoredChunk` 的源追溯字段 MUST 被正确填充

#### Scenario: LightRAG 原生模式下 chunk 携带源信息

- **WHEN** 系统通过 LightRAG 原生查询模式（mix/hybrid/local/global/naive）执行查询
- **THEN** 在结果包装层 MUST 通过 chunk_id 查询 doc_status 后填充源追溯字段

### Requirement: 源文档信息查询接口

系统 SHALL 提供通过 chunk_id 查询源文档信息的接口，支持批量查询以减少数据库访问次数。

#### Scenario: 单个 chunk_id 查询

- **WHEN** 传入一个有效的 chunk_id
- **THEN** 系统 MUST 返回包含 `file_path`、`document_name` 的源文档信息
- **AND** 若 chunk_id 无法找到对应文档，MUST 返回 `file_path: null` 而非抛出异常

#### Scenario: 批量 chunk_id 查询

- **WHEN** 传入多个 chunk_id 的列表
- **THEN** 系统 MUST 在单次查询中返回所有可解析的源文档信息
- **AND** 无法解析的 chunk_id MUST 在结果中标记为未找到而非跳过
