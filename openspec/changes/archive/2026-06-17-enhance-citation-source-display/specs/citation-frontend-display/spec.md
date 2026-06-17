## ADDED Requirements

### Requirement: 引用来源展示面板

前端消息展示 SHALL 在每条 AI 回答下方渲染可折叠的"引用来源"面板，列出该回答引用的所有来源。

#### Scenario: 回答包含引用时展示面板

- **WHEN** AI 回答的 `citations` 字段包含至少一条引用
- **THEN** 回答气泡下方 MUST 显示可点击展开的"引用来源 (N)"区域
- **AND** 展开后 MUST 显示每条引用的源文档名和原文摘录

#### Scenario: 回答不包含引用时不展示面板

- **WHEN** AI 回答的 `citations` 字段为空或不存在
- **THEN** 回答气泡下方 MUST NOT 显示引用来源面板

#### Scenario: 面板默认折叠

- **WHEN** 引用来源面板首次渲染
- **THEN** 面板 MUST 处于折叠状态
- **AND** 折叠状态下 MUST 显示引用数量（如 "引用来源 (3)"）

### Requirement: 引用内联标记渲染

AI 回答文本中的 `[来源 N]` 标记 SHALL 被渲染为可点击的内联元素。

#### Scenario: Markdown 中的引用标记被渲染为链接

- **WHEN** 回答文本包含 `[来源 1]` 标记
- **THEN** 前端 MUST 将该标记渲染为可点击的上标样式元素
- **AND** 点击后 MUST 自动展开引用来源面板并高亮对应的引用条目

#### Scenario: 引用标记不影响正常 Markdown 渲染

- **WHEN** 回答文本同时包含 `[来源 N]` 标记和标准 Markdown 格式（加粗、列表、代码块等）
- **THEN** 标准 Markdown 格式 MUST 正常渲染
- **AND** 只有 `[来源 N]` 标记被替换为自定义组件

### Requirement: 源文档跳转

引用来源面板中的源文档条目 SHALL 支持点击跳转到原文位置。

#### Scenario: 点击源文档名称触发打开

- **WHEN** 用户点击引用面板中某条引用的源文档名称
- **THEN** 系统 MUST 调用后端 `/api/document/open` 端点，传入该引用的 `file_path`
- **AND** 后端 MUST 通过操作系统默认程序打开源文件

#### Scenario: 引用面板展示 chunk 上下文

- **WHEN** 用户点击引用面板中某条引用的"查看上下文"按钮
- **THEN** 系统 MUST 加载并展示该 chunk 在源文档中的前后文段
- **AND** 匹配的关键文本 MUST 被高亮显示

#### Scenario: 文件不存在时的降级处理

- **WHEN** 源文件在指定路径下不存在
- **THEN** 前端 MUST 显示"文件已移动或删除"的提示
- **AND** 仍 MUST 展示已缓存的原文摘录内容
