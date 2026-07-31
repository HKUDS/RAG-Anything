# multimodal-settings-rebuild

## Purpose

定义多模态处理设置变更与知识库执行上下文的生命周期，确保后续任务隔离执行而不破坏现有索引或共享实例。
## Requirements
### Requirement: Settings change for image processing triggers KB rebuild
Personal image-processing settings SHALL be resolved into an immutable task snapshot at submission time rather than changing global settings or clearing all cached KB instances. KB-level visual embedding profile changes SHALL follow the guarded reindex lifecycle.

#### Scenario: Toggle image processing for a future task
- **WHEN** a user saves a new image-processing setting
- **THEN** only later tasks initiated by that user receive the new resolved setting and existing tasks/other users' cached execution state remain unchanged

### Requirement: Settings change for table processing triggers KB rebuild
Personal table-processing settings SHALL be resolved into immutable task snapshots and MUST NOT clear shared KB instances or mutate global configuration.

#### Scenario: Toggle table processing
- **WHEN** a user saves a table-processing setting
- **THEN** subsequent tasks for that user use the setting while persistent KB data and other execution contexts remain unchanged

### Requirement: Settings change for equation processing triggers KB rebuild
Personal equation-processing settings SHALL be resolved into immutable task snapshots and MUST NOT clear shared KB instances or mutate global configuration.

#### Scenario: Toggle equation processing
- **WHEN** a user saves an equation-processing setting
- **THEN** subsequent tasks for that user use the setting while persistent KB data and other execution contexts remain unchanged

### Requirement: KB rebuild preserves existing data
清除缓存 KB 实例时 SHALL NOT 删除持久化的 LightRAG 数据（向量库、图数据库、文档状态）。

#### Scenario: Rebuild after toggle
- **WHEN** KB 实例被清除并重建
- **THEN** `kv_store_doc_status.json`、`vdb_entities.json` 等持久化文件保持不变
- **AND** 已处理文档的文本检索功能正常可用
