# Graph Channel Retrieval

## ADDED Requirements

### Requirement: 实体质量对图谱检索的影响

系统 SHALL 在实体抽取质量提升（通过实体类型白名单和连通性过滤）后，图谱通道返回的 chunk 相关性和精确度相应提升。图谱通道的实体匹配、邻居遍历、候选排序逻辑保持现有行为不变，仅受益于更高质量的输入实体。

#### Scenario: 高质量实体提升检索精度
- **WHEN** 配置了制造领域实体类型白名单（如 Part, Process, Material）
- **AND** 启用了连通性过滤（ENTITY_EXTRACTION_MIN_DEGREE=1）
- **THEN** 实体匹配不再命中噪音实体（如被误抽为实体的数字 "12"）
- **THEN** 邻居遍历不再经过孤立实体节点
- **THEN** 图谱通道返回的 chunk 中噪音文档比例降低

#### Scenario: 未配置时行为不变
- **WHEN** 未配置实体类型白名单和连通性过滤
- **THEN** 实体抽取行为与当前版本完全一致
- **THEN** 图谱通道检索行为与当前版本完全一致
