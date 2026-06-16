# Entity Extraction Configuration

## Purpose

为 LightRAG 实体抽取提供质量控制配置：通过实体类型白名单约束 LLM 抽取行为（事前过滤），通过连通性阈值自动移除孤立实体（事后过滤）。所有配置通过环境变量和设置 API 暴露，默认关闭以保持向后兼容。

## ADDED Requirements

### Requirement: 实体类型白名单配置

系统 SHALL 支持通过 `ENTITY_TYPES` 环境变量配置领域实体类型白名单，以逗号分隔的实体类型列表传递给 LightRAG 的 `addon_params.entity_types`，约束 LLM 在实体抽取时只抽取指定类型的实体。

#### Scenario: 配置制造领域实体类型
- **WHEN** 设置 `ENTITY_TYPES=Part,Assembly,Process,Parameter,Tool,Material,Fault,Standard`
- **THEN** LightRAG 实体抽取仅识别上述类型的实体
- **THEN** 通用实体类型（Person, Organization, Location, Event 等）不再被抽取

#### Scenario: 未配置时保持默认行为
- **WHEN** `ENTITY_TYPES` 未设置或为空字符串
- **THEN** LightRAG 使用内置默认实体类型（Person, Organization, Location, Event, Concept, Method, Content, Data, Artifact, NaturalObject）
- **THEN** 实体抽取行为与当前版本完全一致

#### Scenario: 空值边缘情况
- **WHEN** `ENTITY_TYPES` 设置为空字符串或仅包含空白字符
- **THEN** 系统 SHALL 不传递 `entity_types` 到 LightRAG，使用默认行为

### Requirement: 实体类型配置的 API 暴露

系统 SHALL 在 `GET /api/settings` 响应中包含 `entity_types` 字段，在 `PUT /api/settings` 中接受 `entity_types` 更新，更新后重建全局 RAG 实例以生效。

#### Scenario: 获取实体类型配置
- **WHEN** 调用 `GET /api/settings`
- **THEN** 响应 JSON 包含 `"entity_types": "Part,Assembly,..."` 字段
- **THEN** 未配置时返回 `"entity_types": ""`

#### Scenario: 更新实体类型配置
- **WHEN** 调用 `PUT /api/settings` 且 body 为 `{"entity_types": "Part,Process,Material"}`
- **THEN** 系统设置 `ENTITY_TYPES` 环境变量
- **THEN** 系统重建全局 RAG 实例，新实体类型在下次文档处理时生效

### Requirement: 连通性过滤

系统 SHALL 支持通过 `ENTITY_EXTRACTION_MIN_DEGREE` 环境变量（默认 0，即不过滤）配置实体最小连通度。在实体入库后，系统 SHALL 自动移除 degree 低于此阈值的孤立实体（在知识图谱中无任何边的节点）。

#### Scenario: 移除孤立实体
- **WHEN** 设置 `ENTITY_EXTRACTION_MIN_DEGREE=1`
- **AND** 实体抽取产生了实体 "304"（type=Data，degree=0）
- **THEN** 系统在实体入库后移除 "304" 实体
- **THEN** "304" 实体的 chunk_ids 关联的文本内容保留在 LightRAG 中，仅实体节点被移除

#### Scenario: 默认不过滤
- **WHEN** `ENTITY_EXTRACTION_MIN_DEGREE` 未设置或值为 0
- **THEN** 所有实体（包括 degree=0 的孤立实体）正常保留
- **THEN** 行为与当前版本完全一致

#### Scenario: 高阈值过滤
- **WHEN** 设置 `ENTITY_EXTRACTION_MIN_DEGREE=2`
- **AND** 实体 "扭矩" degree=1（只与一个实体有边）
- **THEN** 实体 "扭矩" 被移除
- **THEN** 只有 degree >= 2 的实体被保留

### Requirement: 配置持久化

系统 SHALL 支持 `ENTITY_TYPES` 和 `ENTITY_EXTRACTION_MIN_DEGREE` 通过 `.env` 文件配置，配置值在服务重启后保持不变。

#### Scenario: 通过 .env 文件配置
- **WHEN** `.env` 文件包含 `ENTITY_TYPES=Part,Process,Material`
- **AND** `.env` 文件包含 `ENTITY_EXTRACTION_MIN_DEGREE=1`
- **THEN** 服务启动后自动读取配置
- **THEN** `GET /api/settings` 返回对应的配置值
