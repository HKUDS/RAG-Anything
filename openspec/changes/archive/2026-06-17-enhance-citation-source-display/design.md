## Context

RAG-Anything 当前在检索增强回答中存在引用来源的"断层"：虽然制造模块 (`raganything/manufacturing/agent/source_tracer.py`) 已实现 `[来源 N]` 格式的结构化引用解析，但通用 RAG 查询管线完全不具备此能力。具体表现为：

1. **数据结构断层**：`ScoredChunk` 仅包含 `chunk_id`、`content`、`score`，缺少源文档追溯信息（`file_path`, `document_name`, `chunk_index`）
2. **提示词断层**：通用 RAG 提示仅模糊要求"基于检索内容回答"，不强制结构化引用格式
3. **响应断层**：`/api/query` 和 `/api/query/stream` 返回的 JSON 中无 `citations` 字段
4. **前端断层**：`AgentChatPage` 将回答作为纯 Markdown 渲染，无引用展示组件

制造模块已有一套可行的引用模式（`CITATION_PATTERN` 正则解析 + `SourceTracer.extract_citations()`），可作为通用化改造的参考基座。

## Goals / Non-Goals

**Goals:**
- 每个检索到的 chunk 携带完整的源文档追溯信息（文件路径、文档名、chunk 序号）
- LLM 在回答中使用 `[来源 N]` 格式标注引用，格式可被程序解析
- 后端解析引用标记，返回结构化的 `citations` 数组（包含来源编号、原文摘录、源文档标识）
- 前端在回答下方展示引用来源面板，每条引用显示原文摘录和源文档名
- 前端引用支持点击跳转到原文位置（通过文件路径定位）
- 流式和非流式查询均返回完整引用信息
- 复用而非重写制造模块的引用解析逻辑

**Non-Goals:**
- 不实现文件预览/内嵌阅读器（点击跳转依赖系统文件关联或 UI 面板）
- 不修改 LightRAG 内部源码（仅在外层包装增强）
- 不改变现有查询 API 的请求格式（向后兼容）
- 不实现引用可信度/置信度评分
- 不实现跨文档的引用关系图谱

## Decisions

### Decision 1: ScoredChunk 扩展方案

**选择**：在 `ScoredChunk` dataclass 中直接新增字段，默认值确保向后兼容。

```python
@dataclass
class ScoredChunk:
    chunk_id: str
    content: str
    score: float
    sources: List[str]              # 现有：检索通道
    # 新增字段
    file_path: Optional[str] = None       # 源文件路径
    document_name: Optional[str] = None   # 源文档名（用于显示）
    chunk_index: Optional[int] = None     # 文档内 chunk 序号
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None
    graph_rank: Optional[int] = None
    graph_entities: List[str] = field(default_factory=list)
```

**备选方案**：新建 `ChunkSourceInfo` 包装类 → **拒绝**，增加不必要的嵌套层级，与现有代码的兼容成本更高。

**理由**：字段平铺在 dataclass 中最简单，新增字段的默认值 `None` 保证现有代码无需修改即可运行。

### Decision 2: Chunk → 源文档映射策略

**选择**：在检索结果构建阶段（`query.py` 的各查询模式中），通过 `chunk_id` 查询 `doc_status` 获取 `file_path` 和 `file_reference`，填充到 `ScoredChunk` 中。

```python
# 伪代码
doc_status = await processor.get_doc_status_by_chunk_id(chunk_id)
chunk.file_path = doc_status.get("file_path")
chunk.document_name = processor._get_file_reference(chunk.file_path)
chunk.chunk_index = int(chunk_id.split("-")[-1])  # chunk_id 格式如 "doc123-chunk-5"
```

**备选方案**：在 `processor.py` 处理阶段将源信息写入 LightRAG chunk 存储 → **拒绝**，需要修改 LightRAG 插入逻辑，侵入性强。

**理由**：在查询阶段按需查询性能可接受（doc_status 已有内存缓存），不改动处理管线。

### Decision 3: 引用格式规范

**选择**：统一使用 `[来源 N]` 格式（与制造模块保持一致），同时要求 LLM 在每个引用后附带被引用的原文摘录。

提示词增强模板：
```
## 引用格式要求（必须严格遵守）
1. 每引用一条检索内容，必须在句末标注 `[来源 N]`，N 是检索文档的序号
2. 回答末尾必须附带【引用来源】部分，格式如下：
   【引用来源】
   [来源 1] 源文档：xxx.pdf | 原文："被引用的具体文本内容..." 
   [来源 2] 源文档：yyy.docx | 原文："被引用的具体文本内容..."
```

**备选方案**：使用 `[1]` 或 `(Author, Year)` 格式 → **拒绝**，`[来源 N]` 更显式，与制造模块一致，中文用户友好。

**理由**：统一的 `[来源 N]` 格式可被 `CITATION_PATTERN` 正则准确解析，且 LLM 对中文提示中的"来源"关键词响应良好。

### Decision 4: 引用解析模块化

**选择**：将 `source_tracer.py` 中的 `extract_citations()` 逻辑提升到 `raganything/` 级别，建立通用的 `citation_parser.py` 模块。

```
raganything/
├── citation_parser.py          # 通用引用解析（从 source_tracer 提炼）
├── manufacturing/
│   └── agent/
│       └── source_tracer.py    # 改为导入 citation_parser
```

**备选方案**：直接在 `query.py` 中内联解析逻辑 → **拒绝**，代码重复，制造模块和通用 RAG 各维护一份。

**理由**：把通用逻辑提升到共享模块，制造模块的 `SourceTracer` 改为调用共享模块，降低耦合。

### Decision 5: 前端引用展示方案

**选择**：在 `AgentChatPage` 消息气泡下方添加可折叠的"引用来源"面板，显示：
- 每条引用的源文档名称（可点击）
- 被引用的原文摘录（高亮显示匹配文本）
- 点击文档名称触发文件定位（通过 vscode://file URI 或浏览器下载链接）

自定义 ReactMarkdown 组件将 `[来源 N]` 渲染为可点击的上标链接，点击后滚动到对应的引用面板条目。

**备选方案**：
- 侧边栏引用面板 → **拒绝**，在紧凑的消息流中分离引用会降低可读性
- 弹窗展示 → **拒绝**，阻断阅读流

**理由**：内联标记 + 折叠面板的组合在 ChatGPT/Perplexity 等产品中经过验证，用户体验最优。

### Decision 6: 跳转行为

**选择**：优先方案 — 点击引用将源文档路径发送到后端 `/api/document/open` 端点，后端通过 `os.startfile()` (Windows) / `open` (macOS) / `xdg-open` (Linux) 打开文件。同时在前端引用面板中展示全文上下文区域（加载该 chunk 周围的文本）。

**备选方案**：
- 纯前端 `vscode://file` 协议 → **拒绝**，仅 VS Code 用户可用
- 纯 `file://` 链接 → **拒绝**，浏览器安全限制

**理由**：后端代理打开文件是最通用的方案，覆盖所有编辑器和文档类型。同时前端面板加载 chunk 上下文提供即时预览能力。

## Risks / Trade-offs

- **[风险] LLM 不遵守引用格式** → **缓解**：提示词中多次强调格式要求 + 在后处理阶段检测 `[来源 N]` 缺失时给 LLM 追加一次"请补充引用来源"的纠正请求
- **[风险] chunk_id 到源文档的映射不总是可用** → **缓解**：LightRAG 原生模式可能不暴露 chunk_id；针对这些模式，在查询包装层预先查询 doc_status 建立映射缓存
- **[风险] 引用面板在前端额外渲染可能影响消息流性能** → **缓解**：引用面板采用懒加载 + 虚拟滚动，仅当用户展开时加载完整内容
- **[风险] 大文档 chunk 数量多导致引用面板过长** → **缓解**：限制最多展示前 10 条引用，超出部分折叠
- **[权衡] 提示词变长增加 token 消耗** → 引用格式要求增加约 200 tokens 的提示词，增幅约 5-10%，在可接受范围
- **[权衡] ScoredChunk 字段增多增加内存占用** → 每个 chunk 新增约 200 bytes（三个可选字段），对千级 chunk 可忽略
