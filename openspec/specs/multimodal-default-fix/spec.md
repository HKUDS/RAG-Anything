# multimodal-default-fix

多模态处理（图片/表格/公式）默认开启。

## ADDED Requirements

### Requirement: Image processing enabled by default
系统 SHALL 在未设置 `ENABLE_IMAGE_PROCESSING` 环境变量时，默认启用图片多模态处理。

#### Scenario: No env var set
- **WHEN** 环境变量 `ENABLE_IMAGE_PROCESSING` 未设置
- **AND** 创建新的 RAGAnything 实例
- **THEN** `config.enable_image_processing` SHALL 为 `True`
- **AND** `ImageModalProcessor` 被注册到 `modal_processors["image"]`

#### Scenario: Env var explicitly set to false
- **WHEN** 环境变量 `ENABLE_IMAGE_PROCESSING=false`
- **THEN** `config.enable_image_processing` SHALL 为 `False`
- **AND** `ImageModalProcessor` 不被注册

### Requirement: Table processing enabled by default
系统 SHALL 在未设置 `ENABLE_TABLE_PROCESSING` 环境变量时，默认启用表格多模态处理。

#### Scenario: No env var set
- **WHEN** 环境变量 `ENABLE_TABLE_PROCESSING` 未设置
- **AND** 创建新的 RAGAnything 实例
- **THEN** `config.enable_table_processing` SHALL 为 `True`
- **AND** `TableModalProcessor` 被注册到 `modal_processors["table"]`

### Requirement: Equation processing enabled by default
系统 SHALL 在未设置 `ENABLE_EQUATION_PROCESSING` 环境变量时，默认启用公式多模态处理。

#### Scenario: No env var set
- **WHEN** 环境变量 `ENABLE_EQUATION_PROCESSING` 未设置
- **AND** 创建新的 RAGAnything 实例
- **THEN** `config.enable_equation_processing` SHALL 为 `True`
- **AND** `EquationModalProcessor` 被注册到 `modal_processors["equation"]`

### Requirement: Default consistency between kb_service and config
`kb_service.py` 中传入 `RAGAnythingConfig` 的多模态默认值 SHALL 与 `config.py` dataclass 的默认值一致。

#### Scenario: Both defaults are true
- **WHEN** 检查 `kb_service.py` 的 `create_rag()` 中 `enable_image_processing` 的 fallback
- **THEN** 其值 SHALL 为 `"true"`（而非 `"false"`）
