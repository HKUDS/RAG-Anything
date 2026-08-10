## 1. 后端设置模型与目录

- [x] 1.1 `DEFAULT_SETTINGS["ingestion"]` 与 legacy 环境层新增 `parsers_by_type: {}`，`ProcessingTaskSettings` 增加 `parsers_by_type` 字段
- [x] 1.2 定义 `PARSER_TYPES = ("pdf", "office", "image")` 与解析器 `supported_types` 能力矩阵常量（docling→pdf/office；mineru/marker/paddleocr→pdf/office/image；opendataloader→pdf；未知/自定义 id 默认 pdf/office/image）
- [x] 1.3 `_parser_catalog()` 每项新增 `supported_types`
- [x] 1.4 校验扩展：`_validate_section` 拒绝未知类型键、非字符串值与不支持组合（含 docling+image）；`_validate_section_against_platform_policy` 对 `parsers_by_type` 非空值应用 `allowed.parsers`
- [x] 1.5 归一化：PATCH 落库前剔除空串键，保证存储/有效值不含空串
- [x] 1.6 后端测试：`tests/test_user_settings_resolution.py` 增加默认 `{}`、优先级、非法组合、allow-list、空串归一化用例；`tests/test_personal_settings_capabilities.py` 断言 `supported_types` 与 ODL 仅 pdf

## 2. 运行时接线

- [x] 2.1 `raganything/raganything.py` 配置新增 `parsers_by_type: dict = {}` 默认
- [x] 2.2 `kb_service.create_rag` 从 `task_settings["ingestion"]["parsers_by_type"]` 读取并传入 `RAGAnything`
- [x] 2.3 `process_document_complete_lightrag_api` 增加 `parsers_by_type` 参数并写入 `self.config.parsers_by_type`
- [x] 2.4 `_effective_parser_name` 改为按扩展名映射类型并按优先级解析（用户覆盖 > PDF_PARSER > 全局）
- [x] 2.5 视频短路：`parse_document` 在解析器实例化前识别视频扩展名并直接生成 video content；ODL 守卫条件改为仅拒绝非 pdf 类型并更新报错文案（缓存键已纳入 effective parser，无需额外工作）
- [x] 2.6 docling+html 修复：`DoclingParser.parse_office_doc` 对 html 系列委托 `parse_html`
- [x] 2.7 新增/扩展 doc_processor 定向测试覆盖 pdf/office/image 映射、全局 ODL + 视频不失败、docling + html 走 parse_html

## 3. 前端个人设置

- [x] 3.1 新增按文件类型解析器选项工具（过滤 supported_types、未安装置灰、目录缺失回退到仅跟随默认）
- [x] 3.2 `PreferencesPage.jsx` 上传/解析区新增 PDF/办公文档/图片文件解析三行下拉（首项跟随默认，图片行文案与多模态开关区分）+ 视频行开关与说明（从多模态 fieldset 移入）
- [x] 3.3 保存/渲染 `parsers_by_type`：PATCH 前剔除空串键、每次 PATCH 携带完整 ingestion draft；「查看已保存值与生效状态」网格加入 `parsers_by_type` 并自定义展示
- [x] 3.4 前端工具单测新增按类型过滤、跟随默认、置灰、回退、空串剔除用例

## 4. 验证与收尾

- [x] 4.1 运行后端定向测试、前端 `node --test frontend/src/utils/*.test.js`、`vite build`
- [x] 4.2 按项目铁律完成专家审查（执行+审查+测试）并修复问题
- [x] 4.3 更新 `PROJECT_SUMMARY.md`（当前状态 + 近期任务记录）
- [x] 4.4 归档提示：与 `restore-chunking-parser-options` 的 delta 重叠，归档时需合并清理同区要求