## Why

提交 `1857767`（2026-07-31 设置整合迁移）重写个人设置页时，把分块策略下拉硬编码为 `recursive`/`fixed` 两项，并把解析器下拉直接渲染平台策略 `allowed.parsers`（迁移 `023` 默认空数组，语义为“不限制”），导致个人设置只能看到 2 种分块策略、解析器下拉为空；同时 `KnowledgeDetailPage` 不再加载策略目录，上传面板的切块方式选择器永远停在“正在读取可用的切块方式…”。后端实际支持 6 种分块策略与 5 种解析器，需要恢复为一致、可用的选项。

## What Changes

- `GET /api/users/me/settings/options` 新增 `parsers`（id/name/available，来自 `raganything.parser.SUPPORTED_PARSERS` 与各解析器 `check_installation()`）和 `chunking_strategies`（id/name/description/cost/cost_level，来自 `raganything.chunking.STRATEGY_META`）两个目录字段。
- 目录按用户可用的 section 投影（仅 ingestion 用户可见）；平台 `allowed.parsers`/`allowed.chunking_strategies` 非空时过滤目录，为空（“不限制”）时展示全部。
- 个人设置页解析器下拉渲染全部 5 种解析器，未安装的置灰；分块策略下拉渲染 6 种规范 id（`fixed_size`/`recursive`/`sentence`/`structure`/`semantic`/`agentic`），显示名与上传面板一致。
- 知识库上传面板重新从 options 接口加载 `chunking_strategies` 目录，恢复切块方式选择器。
- 接口失败时前端回退到最小可用集合（解析器 `docling`；策略 `recursive`/`fixed_size`），保持控件可用。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `personal-settings-center`: 上传与解析分区的分块策略与解析器选项 SHALL 来自服务端目录并按允许列表过滤；空允许列表 SHALL 展示全部支持项；上传面板切块方式选择器 SHALL 始终可用。
- `user-settings-resolution`: settings options 接口 SHALL 返回无密钥的解析器与分块策略目录及安装可用性，且按用户 section 权限与平台允许列表投影。

## Impact

- 后端：`raganything/services/user_settings.py`（`settings_options`、`project_settings_options`）、`raganything/routers/user_settings.py`（`get_my_settings_options`）。
- 前端：`frontend/src/pages/PreferencesPage.jsx`、`frontend/src/pages/KnowledgeDetailPage.jsx`。
- 测试：`tests/test_user_settings_resolution.py`、`tests/test_personal_settings_capabilities.py`、`frontend/src/utils/preferencesPresentation.test.js`。
- 无数据库迁移、无 `/api/settings` 行为变更；平台策略语义（空=不限制）保持不变。
