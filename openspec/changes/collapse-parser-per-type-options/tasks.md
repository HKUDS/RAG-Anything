## 1. 工具与单测

- [x] 1.1 `frontend/src/utils/parserTypeOptions.js` 新增并导出 `summarizeParsersByType(parsersByType)`：空对象/全空值返回「全部跟随默认」；非空时按 `PARSER_FILE_TYPES` 顺序（pdf→office→image）用 `PARSER_TYPE_DISPLAY_LABELS` 输出「已指定：PDF、办公文档」，忽略空值与未知键
- [x] 1.2 `frontend/src/utils/parserTypeOptions.test.js` 增加 `summarizeParsersByType` 用例（空、部分覆盖、未知键），运行 `node --test frontend/src/utils/parserTypeOptions.test.js` 通过

## 2. 页面布局与文案

- [x] 2.1 `frontend/src/pages/PreferencesPage.jsx` ingestion 区：「解析器」标签改为「默认解析器」，行内加 `<small>` 说明「未单独指定时，所有文件类型使用此解析器；未安装的解析器会置灰。」
- [x] 2.2 将 `PARSER_FILE_TYPES` 三行移出主网格，包进 `<details className="preferences-advanced">`，`<summary>` 为「按文件类型指定（可选）」+ 折叠摘要；内部用 `.preferences-field-grid` 保持原两列布局，行 id/htmlFor、onChange、草稿逻辑原样保留
- [x] 2.3 主网格拆为两段：默认解析器 → 启用视频处理；分块策略/分块大小/实体类型/最低关系度；折叠区紧随第一段之后；折叠摘要调用 `summarizeParsersByType(drafts.ingestion?.parsers_by_type ?? effective.ingestion?.parsers_by_type)`
- [x] 2.4 `frontend/src/index.css` 将 `.preferences-advanced summary` 并入既有 summary 规则（含 dark 变体），并补齐折叠区与分块网格之间的垂直间距

## 3. 验证与收尾

- [ ] 3.1 运行 `node --test frontend/src/utils/*.test.js` 与 `frontend` 目录下 `vite build` 通过
- [x] 3.2 按项目铁律完成专家审查（执行+审查+测试）并修复问题；浏览器人工核对：默认折叠、展开三行、摘要随草稿切换、未安装解析器置灰
- [x] 3.3 更新 `PROJECT_SUMMARY.md`（当前状态 + 近期任务记录）
- [x] 3.4 归档提示：与 `parser-per-type-overrides`、`restore-chunking-parser-options`、`enforce-personal-settings-capabilities` 的 `personal-settings-center` delta 重叠，归档时需合并清理同区 requirement
