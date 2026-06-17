## Why

制造智能体的文本问答在返回答案时，附带展示的"相关图片"与用户所提问题缺乏语义关联——当检索文本中未出现"图X"编号引用时，引擎会无差别地返回知识库中的第一张图片，导致图片完全无关。同时，制造智能体的前端页面缺少指引性空状态和入门流程，用户首次使用时不知从何下手。这两个问题叠加，严重影响了制造智能体功能的可用性和可信度。

## What Changes

- **修复图片匹配逻辑**：重写 `QAEngine._match_relevant_images()` 方法，移除"无图号引用时默认返回首图"的兜底逻辑，改为仅在检索文本包含明确图号引用或图片caption与查询语义相关时才返回图片
- **增强图片相关性判断**：新增基于图片路径/caption关键字的语义匹配回退策略，替代无条件的首图返回
- **改进制造智能体前端空状态**：为 Dashboard、Agent QA、Code Parser、Fault Diagnosis 各 Tab 添加有指导意义的空状态提示和操作指引
- **修复快捷提问按钮**：移除 `setTimeout` hack，改用正确的 React 状态更新模式
- **添加制造模块入口指引**：在 Dashboard 页面添加数据导入→知识图谱→智能问答的工作流引导

## Capabilities

### New Capabilities
- `mfg-image-semantic-match`: 制造智能体图片与查询语义匹配——基于 caption/路径关键字进行相关性判断，替代无条件首图返回
- `mfg-onboarding-ux`: 制造智能体前端空状态指引——为 Dashboard、Agent QA、Code Parser、Fault Diagnosis 添加引导性空状态

### Modified Capabilities
- `rag-integration`: QA 引擎的 `_match_relevant_images` 方法行为变更——移除默认首图返回，改为仅在匹配成功时返回图片
- `frontend-visualization`: 制造智能体页面空状态组件化，添加入门操作指引

## Impact

- **后端**: `raganything/manufacturing/agent/qa_engine.py` — `_match_relevant_images()` 方法重写
- **后端**: `server.py:2721-2740` — 图片路径加载逻辑可能需要补充 caption 信息
- **前端**: `frontend/src/pages/ManufacturingAgentPage.jsx` — 空状态组件 + 快捷提问修复
- **前端**: `frontend/src/pages/ManufacturingDashboardPage.jsx` — 工作流引导
- **前端**: `frontend/src/pages/ManufacturingKnowledgePage.jsx` — 空状态改进
