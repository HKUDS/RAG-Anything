# multimodal-settings-rebuild

设置页切换多模态开关时，清除已缓存 KB 实例以确保新配置生效。

## ADDED Requirements

### Requirement: Settings change for image processing triggers KB rebuild
当通过 `PUT /api/settings` 变更 `enable_image` 设置时，系统 SHALL 清除所有已缓存的 KB 实例，使下次访问时以新配置重建。

#### Scenario: Toggle image processing on
- **WHEN** 管理员调用 `PUT /api/settings` 设置 `enable_image=true`
- **THEN** 所有 `kb_instances` 中的缓存实例被删除
- **AND** 下次访问任意 KB 时，以 `enable_image_processing=true` 重新创建 RAGAnything 实例
- **AND** 新实例包含 `ImageModalProcessor`

#### Scenario: Toggle image processing off
- **WHEN** 管理员调用 `PUT /api/settings` 设置 `enable_image=false`
- **THEN** 所有 `kb_instances` 中的缓存实例被删除
- **AND** 下次访问任意 KB 时，以 `enable_image_processing=false` 重新创建 RAGAnything 实例

### Requirement: Settings change for table processing triggers KB rebuild
当通过 `PUT /api/settings` 变更 `enable_table` 设置时，系统 SHALL 清除所有已缓存的 KB 实例。

#### Scenario: Toggle table processing
- **WHEN** 管理员调用 `PUT /api/settings` 设置 `enable_table` 为任意值
- **THEN** 所有 `kb_instances` 中的缓存实例被删除

### Requirement: Settings change for equation processing triggers KB rebuild
当通过 `PUT /api/settings` 变更 `enable_equation` 设置时，系统 SHALL 清除所有已缓存的 KB 实例。

#### Scenario: Toggle equation processing
- **WHEN** 管理员调用 `PUT /api/settings` 设置 `enable_equation` 为任意值
- **THEN** 所有 `kb_instances` 中的缓存实例被删除

### Requirement: KB rebuild preserves existing data
清除缓存 KB 实例时 SHALL NOT 删除持久化的 LightRAG 数据（向量库、图数据库、文档状态）。

#### Scenario: Rebuild after toggle
- **WHEN** KB 实例被清除并重建
- **THEN** `kv_store_doc_status.json`、`vdb_entities.json` 等持久化文件保持不变
- **AND** 已处理文档的文本检索功能正常可用
