## Why

`fix-multimodal-processing` 已修改代码中多模态开关的默认值（`false` → `true`），但 `.env` 文件中缺少显式的环境变量声明。代码默认值依赖隐式行为，存在被意外覆盖的风险。需要将多模态默认开启固化到 `.env` 配置文件，确保配置意图持久化且可审计。

## What Changes

- 在 `.env` 文件中显式声明 `ENABLE_IMAGE_PROCESSING=true`、`ENABLE_TABLE_PROCESSING=true`、`ENABLE_EQUATION_PROCESSING=true`
- 确保 `load_dotenv` 加载后这些环境变量在 `os.environ` 中生效
- 验证上传管线：文档上传 → 解析 → 多模态分离 → VLM 描述生成 → 实体/关系入库，全链路无需人工干预

## Capabilities

### New Capabilities

- `multimodal-env-declaration`: 在 `.env` 文件中显式声明多模态环境变量，使配置意图持久化且可审计

### Modified Capabilities

<!-- No existing spec requirements are changing. The new behavior is additive. -->

## Impact

- `.env` 文件：新增 3 行配置（`ENABLE_IMAGE_PROCESSING`、`ENABLE_TABLE_PROCESSING`、`ENABLE_EQUATION_PROCESSING`）
- `raganything/config.py`：现有默认值无需改动
- `raganything/services/kb_service.py`：现有逻辑无需改动
- `raganything/processor/doc_processor.py`：上传管线无需改动（已验证正确）
