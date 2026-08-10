## Context

个人设置目前只有一个全局解析器字段（`ingestion.parser`，默认 `docling`），部署端另有 `PDF_PARSER` 环境变量对 PDF 单独覆盖。`raganything/processor/doc_processor.py::_effective_parser_name` 目前按扩展名只区分“PDF（走 pdf_override）与非 PDF（走全局）”两档，随后按扩展名分发到 `parse_pdf` / `parse_office_doc` / `parse_image`（不支持时回退 MinerU）/ 视频直通多模态管线；`opendataloader` 有“仅 PDF”硬性守卫。设置以 JSONB 存储于 PostgreSQL，按 legacy 环境层 → 平台默认 → 资源设置 → 用户存储 → 请求覆盖的优先级合并，`DEFAULT_SETTINGS` 为每个键提供默认值。`GET /users/me/settings/options` 已下发 `parsers` 目录（id/name/available）与 `chunking_strategies` 目录，并按平台 `allowed.parsers` 过滤。

## Goals / Non-Goals

**Goals:**
- 为 PDF / 办公文档（doc/docx/ppt/pptx/xls/xlsx/html/htm/xhtml）/ 图片三类提供“跟随全局默认或指定解析器”的用户级覆盖。
- options 目录为每个解析器提供 `supported_types`，前端只展示真正支持该类型的解析器。
- 校验拒绝未知类型键、不支持组合（如 `opendataloader` 配 `office`/`image`、`docling` 配 `image`）及平台 allow-list 之外的值；空串键在持久化前归一化剔除。
- 运行时按扩展名映射类型，优先级：`parsers_by_type[type]` > `PDF_PARSER`（仅 pdf）> 全局 `parser`；视频在任何配置下都不实例化解析器；ODL 仅 PDF 守卫保留。
- 前端保持傻瓜式：每类型下拉首项「跟随默认（推荐）」，未安装解析器置灰；视频行只显示开关与说明；图片文件解析与文档内图片多模态处理明确区分。

**Non-Goals:**
- 不支持按单个格式（docx/pptx/xlsx 分开）配置、不支持知识库级覆盖、不给视频选择解析器、不改分块策略与多模态开关模型。
- 不做数据迁移：旧行经默认合并自动获得 `parsers_by_type={}`。
- 不新增运行时安装预检（目录已按安装可用性置灰；runtime 行为与现有 `PDF_PARSER` 一致）。

## Decisions

1. **字段形态**：`ingestion` 新增单一字典字段 `parsers_by_type`（键限 `pdf`/`office`/`image`，值为解析器 id 或空串 = 跟随全局）。相比拆成三个标量字段，字典让 schema 保持封闭、未知键可被校验拒绝、PATCH 面更小，且自动纳入 fingerprint。**归一化**：后端在 PATCH 校验/落库前剔除空串键（存储值不含空串），前端 PATCH 前同样剔除；这样“跟随默认”行既不产生伪 dirty，也不会污染存储。
2. **类型归类**：`office` 覆盖所有走 `parse_office_doc` 的扩展名（office + html 系列）；`image` 覆盖所有图片扩展名；`video` 是独立类型（不经过解析器）；txt/md/其他为 generic，继续跟随全局解析器。`_effective_parser_name` 返回“解析器名”之外，还需按类型决定是否允许 ODL 与是否需要实例化解析器。
3. **能力矩阵**（依据各解析器实际实现）：`docling → ["pdf","office"]`、`mineru/marker/paddleocr → ["pdf","office","image"]`、`opendataloader → ["pdf"]`。矩阵缺失的自定义解析器 id 默认允许 `["pdf","office","image"]`（目录不展示自定义 id，PATCH 校验仍可放行）。office 类型内子格式支持因解析器而异（如 marker 对 `.ppt/.xls` 需转换），运行时失败属预期，不做单格式粒度。
4. **优先级**：用户级按类型覆盖 > 部署端 `PDF_PARSER`（仅 pdf）> 全局 `parser`。用户显式选择优先于部署环境变量；平台仍可用 `allowed.parsers` allow-list 治理可选项（空 = 不限制）。注意 `PDF_PARSER` 在 `config.py` 是进程启动时读取，不是运行时动态层。
5. **运行时接线**：`kb_service.create_rag` 从任务快照 `ingestion.parsers_by_type` 读取并传入 `RAGAnything`，写入 `config.parsers_by_type`；`process_document_complete_lightrag_api` 同样在收到参数时写入；`_effective_parser_name` 改为“扩展名 → 类型 → 优先级解析”。缓存键已通过 `_effective_parse_config` 纳入 effective parser，无需额外工作。
6. **视频短路与 ODL 守卫**：`parse_document` 在解析器实例化之前先判断视频扩展名并直接生成 video content（任何解析器配置下都不实例化解析器）；ODL 守卫条件改为“effective_parser 为 opendataloader 且类型不是 pdf 时拒绝”，报错文案不再限定“仅通过 PDF_PARSER”（per-type pdf 覆盖也可合法选择 ODL）。
7. **docling + html 修复**：`DoclingParser.parse_office_doc` 对 `HTML_FORMATS` 扩展名委托给 `parse_html`（当前 doc_processor 把 html 分发给 `parse_office_doc`，docling 会拒绝，属于既有缺陷）；其他解析器行为不变。
8. **前端**：`PreferencesPage` 的上传/解析区在“默认解析器”下方新增三行下拉（PDF / 办公文档 / 图片文件解析），每行首项「跟随默认（推荐）」值为空串，其后仅列 `supported_types` 含该类型的解析器，`available=false` 置灰并标注「未安装」；图片行文案明确为「图片文件解析（jpg/png/…）」并注明与多模态区的「图片处理」开关（文档内图片）不同；视频行显示「启用视频处理」开关与说明文案，从原多模态 fieldset 移入本区，多模态 fieldset 保留图片/表格/公式并标注“文档内多模态处理”。options 请求失败时按类型下拉仅保留「跟随默认」，全局下拉回退「当前生效解析器 + docling」（与现有 `fallbackParserOptions` 一致）。
9. **PATCH 语义**：沿用现有“整段替换”语义（`values:null` 表示恢复继承）；前端每次 PATCH 携带完整 ingestion draft（含 `parsers_by_type`），避免误清空。若后续出现部分 PATCH 调用方，再评估后端字段级合并。

## Risks / Trade-offs

- [`personal-settings-center`/`user-settings-resolution` 主规格存在未归档的并行 delta（restore-chunking-parser-options）] → 本变更对这两个能力一律使用 ADDED Requirements，不改写既有要求块；归档时两变更会产生同区重叠要求，收尾时在归档阶段合并清理。
- [旧任务/旧调用路径没有 `config.parsers_by_type`] → `RAGAnything` 配置默认 `{}`，并在 `create_rag` 与 `process_document_complete_lightrag_api` 两处写入。
- [绕过前端直接 PATCH 非法组合] → PATCH 校验拒绝 + 运行时 ODL 守卫双重防线。
- [用户覆盖与 `PDF_PARSER` 优先级语义被误解] → 在设置页说明与 spec 中明确：用户显式选择优先于环境变量。
- [整段替换语义可能清空未随 PATCH 提交的字段] → 前端全量 draft 提交 + 后端定向测试覆盖。

## Migration Plan

- 无需数据库迁移：`DEFAULT_SETTINGS` 与 legacy 环境层为 `parsers_by_type` 提供 `{}` 默认，旧 JSONB 行自动合并。
- 部署顺序：后端代码 + 前端构建 → 重启后端（8001）→ 浏览器验证个人设置三个下拉、视频行说明与上传面板行为不变。

## Open Questions

- 无阻塞性未决问题。