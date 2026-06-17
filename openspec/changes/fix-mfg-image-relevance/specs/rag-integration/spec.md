# RAG Integration (Delta)

## MODIFIED Requirements

### Requirement: QA 引擎对接 RAG 检索
QA 引擎 SHALL 通过依赖注入方式接入服务器已有的 RAG-Anything 检索引擎实例，实现真正的向量+BM25 混合检索。QA 引擎的图片匹配 SHALL 使用三级策略（图号精确匹配 → Caption 关键字匹配 → 路径关键字匹配），当三级匹配均失败时 SHALL 不返回图片而非返回无关图片。

#### Scenario: 检索增强回答
- **WHEN** 用户通过 API 发起文本问答
- **THEN** QA 引擎 SHALL 先调用 RAG-Anything 检索引擎获取 Top-K 相关文档，再基于检索结果生成回答并附带来源引用

#### Scenario: 图号匹配成功返回图片
- **WHEN** 检索文本中包含 "图3" 或 "Figure 3" 等图号引用
- **THEN** QA 引擎 SHALL 按图号映射返回对应的 1-2 张图片

#### Scenario: 无图号引用时按语义匹配
- **WHEN** 检索文本中不存在任何图号引用
- **THEN** QA 引擎 SHALL 使用 caption/路径关键字与查询进行 jieba 分词交集匹配，返回匹配成功的图片（最多 2 张），若全部无交集则返回空数组

#### Scenario: 检索超时降级
- **WHEN** RAG 检索耗时超过 3 秒
- **THEN** 系统 SHALL 取消检索，降级为无检索模式，回答中注明"检索超时，回答可能不完整"

#### Scenario: 检索为空时的处理
- **WHEN** RAG 检索返回 0 条结果
- **THEN** 系统 SHALL 返回预定义降级消息"当前知识库未覆盖该问题"
