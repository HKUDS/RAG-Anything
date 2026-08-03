## ADDED Requirements

### Requirement: 源文档追溯映射从持久化存储重建

系统 SHALL 在服务重启后从持久化存储重建 chunk→源文档映射，确保引用来源显示真实文档名而非“未知文档”。

#### Scenario: PG 存储下重启后引用保留文档名

- **WHEN** 知识库使用 PGDocStatusStorage（存储对象具有非空 `db` 属性）且服务重启后首次查询
- **THEN** 系统 MUST 按 `doc_status_store.workspace` 从 `LIGHTRAG_DOC_STATUS` 读取 `file_path` 与 `chunks_list` 重建映射
- **AND** 引用来源 MUST 显示真实文档名（经 `_get_file_reference` 生成），而非“未知文档-chunk-xxxx”

#### Scenario: 缓存定期刷新以纳入新上传文档

- **WHEN** 重建完成超过 60 秒刷新周期后发生查询
- **THEN** 系统 MUST 重新从持久化存储刷新映射
- **AND** 新上传文档的 chunk 引用 MUST 解析为真实文档名

#### Scenario: 单行数据损坏不影响整体重建

- **WHEN** 某文档的 `chunks_list` 无法解析（为损坏字符串或非法 JSON）
- **THEN** 系统 MUST 跳过该行并继续处理其余文档
- **AND** 整体重建 MUST 仍标记成功

#### Scenario: 重建失败可重试

- **WHEN** 持久化查询抛出异常（连接不可用、表未创建）
- **THEN** 系统 MUST 不标记构建成功
- **AND** 下次查询 MUST 重新尝试重建

### Requirement: JSON 存储源追溯回归兼容

系统 SHALL 在非 PG（JSON）存储下保持原有 `_data` 内存重建路径。

#### Scenario: JSON 存储缓存重建

- **WHEN** doc_status 存储为 JSON 实现且无 `db` 属性
- **THEN** 重建 MUST 使用 `doc_status._data` 路径
- **AND** 不得抛出 `AttributeError` 或导致缓存永不构建
