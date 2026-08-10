## Why

「上传与解析」区目前把「全局解析器」和 PDF/办公/图片三个按类型下拉平铺展示，彼此没有成组标题或说明文字，用户难以判断该改哪一行，与「傻瓜式简单易上手」的目标冲突。同一页面检索区已采用「预设 + 高级展开」的渐进式设计，解析器区也应照此收敛：默认只呈现一个「默认解析器」，按类型覆盖收进可展开的「按文件类型指定（可选）」，并用折叠摘要告知当前是否已有覆盖。

## What Changes

- 前端呈现调整（仅 `frontend/`，后端/接口/数据结构/已保存值均不变）：
  - 「解析器」标签改为「默认解析器」，行内加说明文字：未单独指定时所有文件类型使用此解析器；未安装的解析器会置灰。
  - PDF/办公/图片三个按类型下拉移出主网格，收进 `<details>`「按文件类型指定（可选）」；内部保持原两列布局，行 id、onChange、草稿逻辑原样保留。
  - 主网格拆为两段：第一段「默认解析器 → 启用视频处理」，第二段「分块策略/分块大小/实体类型/最低关系度」；折叠区作为两者之间的独立块，紧随第一段之后，视觉上归组。
  - 折叠摘要由新增工具 `summarizeParsersByType(parsers_by_type)` 生成：无覆盖时显示「全部跟随默认」，有覆盖时显示「已指定：PDF、办公文档」（用中文类型标签，忽略空值与未知键）。
  - 折叠区 `<summary>` 样式并入既有 summary 规则（含 dark 变体），并补齐与分块网格之间的垂直间距。
- 不做任何数据迁移；已保存的 `parsers_by_type` 与「查看已保存值与生效状态」网格不受影响。

## Capabilities

### New Capabilities
<!-- 无新能力，纯呈现调整 -->

### Modified Capabilities
- `personal-settings-center`: 上传/解析区的解析器选择从平铺 4 行改为「默认解析器一行 + 按类型折叠区」，并新增说明文案与折叠摘要；行为与保存值语义不变。

## Impact

- 前端：`frontend/src/pages/PreferencesPage.jsx`（ingestion 区布局与文案）、`frontend/src/index.css`（折叠摘要样式与间距）、`frontend/src/utils/parserTypeOptions.js`（新增 `summarizeParsersByType`）及对应单测 `frontend/src/utils/parserTypeOptions.test.js`。
- 不改动：多模态 fieldset、「查看已保存值与生效状态」网格、上传面板、后端服务、接口与迁移。