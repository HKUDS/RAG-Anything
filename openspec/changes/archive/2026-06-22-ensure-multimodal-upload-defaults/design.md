## Context

`fix-multimodal-processing` 已将代码中 `enable_image_processing`、`enable_table_processing`、`enable_equation_processing` 的默认值从 `False`/`"false"` 改为 `True`/`"true"`。这些默认值分布于三处：

| 位置 | 机制 | 当前值 |
|------|------|--------|
| `config.py:73-85` | dataclass `field(default=...)` | `True` |
| `admin.py:321-323` | `os.getenv(..., "true")` | `"true"` |
| `kb_service.py:285-287` | `os.getenv(..., "true")` | `"true"` |

三者一致，但缺少 `.env` 文件的显式声明。如果运维人员或自动化脚本覆盖环境变量（如 `export ENABLE_IMAGE_PROCESSING=false`），会意外关闭多模态处理。

## Goals / Non-Goals

**Goals:**
- 在 `.env` 中显式声明三个多模态环境变量
- 确保 `load_dotenv(override=False)` 不覆盖已设置的外部环境变量，但为缺失的变量提供默认值
- 上传管线端到端验证（手动测试）

**Non-Goals:**
- 不修改代码逻辑（默认值已是正确的）
- 不修改 KB 实例缓存逻辑（已在 `_process_uploaded_file` 中正确清除）
- 不新增 API 端点

## Decisions

### Decision 1: .env 中使用 `true` 字符串

`admin.py` 和 `kb_service.py` 使用 `os.getenv("ENABLE_IMAGE_PROCESSING", "true").lower() == "true"` 模式读取。`.env` 中必须使用小写 `true` 字符串（而非 Python 的 `True`），以保持与 `os.getenv` + `.lower() == "true"` 解析模式一致。

### Decision 2: 不修改 `load_dotenv` 的 `override` 参数

默认 `override=False` 是正确的行为——外部环境变量（如容器编排中的注入）优先于 `.env` 文件。如果用户已显式设置 `ENABLE_IMAGE_PROCESSING=false`，那说明用户有意禁用，`.env` 不应覆盖。

### Decision 3: 变更范围最小化

按照 Minimal Change Engineer 原则，此变更仅涉及 `.env` 文件的 3 行新增。代码逻辑已验证正确，无需改动。

## Risks / Trade-offs

- [风险] 用户已在环境中设置不同的值 → 缓解：`.env` 的 `override=False` 不会覆盖外部环境变量
- [风险] `.env` 文件被误删除 → 缓解：代码默认值已是 `True`，`.env` 缺失不影响功能

## Migration Plan

1. 编辑 `.env` 文件，在文件末尾添加 3 行配置
2. 重启服务器使环境变量生效（`.env` 在服务器启动时加载）
3. 上传测试文档验证多模态自动处理
