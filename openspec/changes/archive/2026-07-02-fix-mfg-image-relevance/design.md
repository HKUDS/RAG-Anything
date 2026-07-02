## Context

制造智能体（Manufacturing Agent）的核心 QA 流程：用户提问 → RAG 检索上下文 → LLM 生成回答 → 附带图片/引用。当前 `QAEngine._match_relevant_images()` 方法基于文本中的"图X"编号引用匹配图片，当检索文本中不存在图号引用时，无条件返回知识库首张图片（`matched_fig_numbers = {1}`），导致显示与问题无关的图片。

前端方面，制造智能体三个页面（Dashboard、AgentPage、KnowledgePage）在数据为空时展示简单的占位符文本，缺少引导用户完成数据导入→建图→问答的完整工作流指引。快捷提问按钮使用 `setTimeout(() => handleQASend(), 50)` hack，依赖竞态条件而非 React 状态更新。

## Goals / Non-Goals

**Goals:**
- 修复 `_match_relevant_images` 的默认首图返回逻辑，仅在有明确图号引用或语义匹配时返回图片
- 新增基于图片路径/caption 关键字与查询文本的交叉匹配作为回退策略
- 为制造智能体前端页面添加有指导意义的空状态组件
- 修复快捷提问按钮的状态管理问题

**Non-Goals:**
- 不引入新的图片向量化/embedding 语义相似度模型（复杂度过高，超出中等范围修复）
- 不重构整个 QA 引擎架构
- 不修改制造智能体以外的页面

## Decisions

### Decision 1: 图片匹配改为三级策略

**选择**: 三级匹配策略替代当前的单级图号匹配
1. **图号精确匹配**（保留）: 从检索文本+query 中提取 "图1-99" / "Figure 1-99" 引用，按序映射
2. **Caption 关键字交集匹配**（新增）: 当无图号匹配时，从 parse cache 中提取图片 caption 文本，与 query 做 jieba 分词后的关键字交集匹配，保留交集 ≥1 的图片
3. **路径关键字匹配**（新增）: 当 caption 不可用时，从图片文件名/路径中提取关键字与 query 匹配

**理由**: 图号匹配在制造技术文档场景（"如图12所示"）中常见且准确，caption/路径匹配作为回退提供最低限度的相关性保证，避免引入重型模型依赖。

**替代方案考虑过的**: 
- VLM 图片相关性判断 → 每次查询需要额外 VLM API 调用，延迟和成本不可接受
- CLIP 多模态向量相似度 → 需要额外模型依赖，超出中等修复范围
- 直接删除图片展示 → 丢失已正确匹配的场景，回退过度

### Decision 2: 空状态组件化为 `<EmptyState>` 

**选择**: 抽取可复用的 `<EmptyState>` 组件，根据 Tab 类型显示不同的引导文案和操作按钮

**理由**: 三个制造页面有相似的空状态展示需求，组件化避免重复代码

### Decision 3: 快捷提问使用 `useCallback` + state setter 直接传参

**选择**: 将 `handleQASend` 改为 `handleQASend(text?: string)` 接受可选参数，快捷按钮直接调用 `handleQASend(questionText)` 而非修改 input state 后 setTimeout

**理由**: 消除 setTimeout 竞态条件，让 React 的状态更新机制保证正确性

## Risks / Trade-offs

- [Risk] Caption 关键字匹配可能遗漏语义相关但用词不同的图片 → Mitigation: 使用 jieba 分词降低词形变化影响，且三级策略的最坏情况是不返回图片而非返回错误图片
- [Risk] parse cache 中的图片 caption 可能为空或质量低 → Mitigation: 当 caption 不可用时回退到路径/文件名关键字匹配
- [Trade-off] 不再默认返回图片意味着某些原本"恰好"正确的场景也不再展示图片 → 接受此trade-off：宁可少展示也不展示错误的图片
