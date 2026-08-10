## Why

个人设置目前只有一个全局解析器（默认 docling），另加部署端 `PDF_PARSER` 环境变量对 PDF 单独覆盖。用户希望按文件类型（PDF / 办公文档 / 图片）分别指定解析器，视频保持“启用/关闭”语义，让上传与解析配置更直观、不易配错——例如把 PDF 专属的 OpenDataLoader 选到 docx 上会直接解析失败。

## What Changes

- 后端 `ingestion` 设置新增 `parsers_by_type` 字段：键限 `pdf`/`office`/`image`，值为解析器 id 或空串（空串/缺省 = 跟随全局；txt/md/其他格式一律跟随全局）。持久化前剔除空串键，保证存储值不含空串。
- `GET /users/me/settings/options` 的 `parsers` 目录每项新增 `supported_types`（如 `opendataloader → ["pdf"]`），前端据此只展示真正支持该类型的解析器。
- 校验扩展：拒绝未知类型键、拒绝“解析器不支持该类型”的组合（如 `opendataloader` 配 `office`/`image`、`docling` 配 `image`）；平台 allow-list `allowed.parsers` 对 `parsers_by_type` 每个非空值同样生效（空数组 = 不限制）。
- 运行时 `_effective_parser_name` 按扩展名映射类型，优先级：`parsers_by_type[type]` > 环境变量 `PDF_PARSER`（仅 pdf，进程启动时读取）> 全局 `parser`。视频在解析器实例化前短路（任何解析器配置下都不经解析器）；OpenDataLoader 仅 PDF 的硬性守卫保留并更新报错文案。
- 修复既有缺陷：docling 处理 html/htm/xhtml 时改走 `parse_html`（当前被错误分发到 `parse_office_doc` 会失败）。
- 前端「上传与解析」新增「按文件类型」区：PDF / 办公文档 / 图片三个下拉，首项「跟随默认（推荐）」，未安装的解析器置灰并标注「未安装」；视频行显示「启用视频处理」开关并说明“视频不经解析器，自动抽帧与转写”。图片下拉标注「图片文件解析」，与多模态区「文档内图片处理」开关明确区分。
- 接口与数据向后兼容：旧设置行经默认合并自动获得 `{}`，无需数据迁移。

## Capabilities

### New Capabilities
- `parser-per-type-overrides`: 按文件类型的解析器覆盖配置模型、能力目录与运行时分发规则。

### Modified Capabilities
- `personal-settings-center`: 上传/解析区新增按文件类型解析器选择与视频处理说明，保持傻瓜式默认。
- `user-settings-resolution`: `ingestion` 模式新增 `parsers_by_type` 字段（空串键归一化）；options 的 `parsers` 目录新增 `supported_types`，并纳入平台 allow-list 过滤与校验。

## Impact

- 后端：`raganything/services/user_settings.py`（设置模型/目录/校验/归一化）、`raganything/processor/doc_processor.py`（运行时解析器分发、视频短路、docling+html 修复）、`raganything/services/kb_service.py` 与 `raganything/raganything.py`（配置传递）。
- 前端：`frontend/src/pages/PreferencesPage.jsx` 与相关工具/测试。
- 测试：`tests/test_user_settings_resolution.py`、`tests/test_personal_settings_capabilities.py`、doc_processor 定向测试、前端工具单测与 `vite build`。