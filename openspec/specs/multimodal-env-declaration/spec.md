## ADDED Requirements

### Requirement: Multimodal env vars declared in .env
`.env` 文件 SHALL 显式声明 `ENABLE_IMAGE_PROCESSING=true`、`ENABLE_TABLE_PROCESSING=true`、`ENABLE_EQUATION_PROCESSING=true` 三个环境变量，使多模态默认开启在配置层面持久化。

#### Scenario: Env file contains explicit declarations
- **WHEN** 检查 `.env` 文件
- **THEN** SHALL 包含 `ENABLE_IMAGE_PROCESSING=true` 行
- **AND** SHALL 包含 `ENABLE_TABLE_PROCESSING=true` 行
- **AND** SHALL 包含 `ENABLE_EQUATION_PROCESSING=true` 行

#### Scenario: Env vars read at server startup
- **WHEN** 服务器启动并加载 `.env` 文件（`load_dotenv`）
- **THEN** `os.environ["ENABLE_IMAGE_PROCESSING"]` SHALL 为 `"true"`
- **AND** `os.environ["ENABLE_TABLE_PROCESSING"]` SHALL 为 `"true"`
- **AND** `os.environ["ENABLE_EQUATION_PROCESSING"]` SHALL 为 `"true"`

### Requirement: KB instance respects current env vars
创建 KB 实例时，`RAGAnythingConfig` 的多模态配置 SHALL 从当前 `os.environ` 读取，而非使用硬编码默认值或过期缓存。

#### Scenario: New KB instance gets current env var values
- **WHEN** `os.environ["ENABLE_IMAGE_PROCESSING"]` 为 `"true"`
- **AND** 调用 `create_rag()` 创建新的 KB 实例
- **THEN** 实例的 `config.enable_image_processing` SHALL 为 `True`
- **AND** `modal_processors["image"]` SHALL 被注册

#### Scenario: Env var change takes effect after server restart
- **WHEN** `.env` 中 `ENABLE_IMAGE_PROCESSING=true` 已配置
- **AND** 服务器已重启
- **AND** 新文档上传到知识库
- **THEN** 文档的多模态内容（图片/表格/公式）SHALL 自动被 VLM 处理
