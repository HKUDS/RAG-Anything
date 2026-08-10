## Context

「上传与解析」区在上一轮 `parser-per-type-overrides` 中新增了全局解析器 + PDF/办公/图片三个按类型下拉，当前四行平铺在同一 `preferences-field-grid` 中，没有成组标题或说明，普通用户容易困惑。同一页面的检索区已用「预设四选一 + 仅 custom 展开」的渐进式设计；本 change 沿用同一思路收敛解析器区。改动纯前端，不触及后端、接口与数据。

## Goals / Non-Goals

**Goals:**
- 默认只呈现「默认解析器」一行并加说明，降低认知负担。
- 按类型覆盖收进可展开区，折叠时用摘要告知当前是否已有覆盖。
- 保留全部既有行为：行 id、选项过滤、未安装置灰、草稿与保存语义。

**Non-Goals:**
- 不改后端、`/users/me/settings/options` 接口、存储结构与已保存值。
- 不改上传面板、多模态 fieldset 与「查看已保存值」网格。
- 不引入新的折叠组件或 CSS 体系。

## Decisions

- **使用原生 `<details>`/`<summary>` 折叠**，而不是条件渲染或自研组件：页面已有三处 `<details>` 用法（模型技术详情、ingestion 与 retrieval 的已保存值状态），原生语义可折叠、可访问，零新增状态管理。复用既有 `.preferences-advanced` 间距类。
- **主网格拆分而非嵌套**：默认解析器 + 启用视频处理放第一个 `.preferences-field-grid`，分块策略/大小/实体/最低关系度放第二个；折叠区作为两者之间的独立块，内部再用 `.preferences-field-grid` 保持三行两列原布局。避免在网格单元里塞 `<details>` 导致布局变形，同时保证解析器相关控件视觉相邻。
- **摘要逻辑放 `parserTypeOptions.js`** 新增纯函数 `summarizeParsersByType(parsersByType)`：空/全空返回「全部跟随默认」，否则用 `PARSER_TYPE_DISPLAY_LABELS` 拼出「已指定：PDF、办公文档」，忽略未知键。纯函数便于单测，与既有 `resolveParserOptionsByType` 等工具同文件。
- **文案**：全局行标签「解析器」→「默认解析器」，`<small>` 说明「未单独指定时，所有文件类型使用此解析器；未安装的解析器会置灰。」；折叠标题「按文件类型指定（可选）」。
- **折叠与摘要规范**：折叠区默认折叠（摘要已承担提示职责）；摘要按 `PARSER_FILE_TYPES` 顺序（pdf→office→image）迭代而非 `Object.entries`，保证输出顺序稳定并天然忽略未知键；调用优先级 `drafts.ingestion?.parsers_by_type ?? effective.ingestion?.parsers_by_type`，undefined 回退 effective、`{}` 即「全部跟随默认」，草稿变化实时反映。
- **折叠摘要样式归属**：`.preferences-advanced` 仅有 margin-top，`<summary>` 会退化为 UA 默认样式；将 `.preferences-advanced summary` 并入既有 summary 规则（含 dark 变体，参照 `.preferences-state-details summary`），并补齐折叠区与分块网格之间的垂直间距（`frontend/src/index.css`）。

## Risks / Trade-offs

- [折叠后功能可见性下降] → 折叠摘要显示覆盖状态（反映草稿与已保存值），展开交互成本仅一次点击；文档型默认路径（跟随默认）仍是一行可见。
- [布局拆分导致视觉间距变化] → 复用既有 `.preferences-field-grid` 与 `.preferences-advanced` 样式，补齐折叠区与分块网格间距；构建后人工核对。
- [行 id 被外部引用/测试依赖] → 三个按类型行保持原 id（`ingestion-parser-pdf` 等），仅移动 DOM 位置，不改变标识。