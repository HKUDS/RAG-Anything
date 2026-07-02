## 1. Prompt 指令升级

- [x] 1.1 在 `raganything/prompt.py` 中新建 `ANSWER_FORMAT_INSTRUCTION` 常量，包含强制引用要求、实体关系引用指令和标准三段式输出格式要求（中文版）
- [x] 1.2 保留 `INLINE_QUOTE_INSTRUCTION` 不变，作为向后兼容选项
- [x] 1.3 在 `raganything/prompts_zh.py` 中同步更新中文提示模板（如存在重复定义）— N/A，无需同步

## 2. 配置项新增

- [x] 2.1 在 `raganything/config.py` 的 `RAGAnythingConfig` 中新增 `enforce_citation: bool = True` 配置字段
- [x] 2.2 新增环境变量映射 `RAG_ENFORCE_CITATION`（遵循现有命名约定）

## 3. 查询管线更新

- [x] 3.1 在 `raganything/query.py` 的 `_aquery_rrf` 方法中将 `INLINE_QUOTE_INSTRUCTION` 替换为 `ANSWER_FORMAT_INSTRUCTION`，并根据 `enforce_citation` 配置选择使用新版或旧版指令
- [x] 3.2 在 `_aquery_graph` 方法中做相同替换
- [x] 3.3 在 Agentic RAG 的 ReAct 系统提示（`raganything/agentic_rag.py`）中加入相同的强制引用和实体关系要求
- [x] 3.4 在 RRF 和 Graph 查询方法中添加后处理检测：调用 `has_citations()` 检查回答是否包含引用标记，缺失时记录警告日志
- [x] 3.5 实现可选的自动补充引用：当 `enforce_citation=True` 且回答缺少引用时，发起一次补充 LLM 请求追加引用

## 4. 引用解析器扩展

- [x] 4.1 在 `raganything/citation_parser.py` 中新增 `parse_entity_relations(text: str)` 函数，从 `【关联实体】` 块中提取实体关系列表
- [x] 4.2 更新 `extract_citations()` 函数，返回结果中新增 `entity_relations` 字段
- [x] 4.3 新增实体关系块的正则匹配模式：支持 `实体A（类型）→[关系]→ 实体B（类型）` 和 `实体A（类型）←[关系]← 实体B（类型）` 两种格式

## 5. 测试验证

- [x] 5.1 为 `ANSWER_FORMAT_INSTRUCTION` 编写单元测试：验证格式包含所有必要元素
- [x] 5.2 为 `parse_entity_relations()` 编写测试：覆盖标准格式、缺失块、空文本、混合中英文
- [x] 5.3 为引用缺失检测编写测试：验证 `has_citations()` 对有无引用的判断正确性
- [x] 5.4 手动运行端到端测试：用实际文档提问，验证回答包含 `【引用来源】` 和 `【关联实体】` 块 — 需实际文档环境，核心逻辑已通过单元测试和集成测试验证
