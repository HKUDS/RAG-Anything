## Context

RAG-Anything 是 React 18 + Vite 5 + Tailwind CSS 3 的单页应用，后端为 Python FastAPI。现有导航栏有 7 个页面入口（智能体/知识库/查询/制造智能体/设置/监控/用户管理）。需要新增工作流编排页面，与现有架构保持一致。

## Goals / Non-Goals

**Goals:**
- DAG 画布：拖拽节点、连线、缩放平移、删除、保存
- 节点配置：侧边面板，按节点类型显示专用表单
- 工作流持久化：JSON 文件存储，CRUD API
- 至少 6 种内置节点类型（文档输入、文本分割、嵌入、检索、LLM、输出）

**Non-Goals:**
- 不实现工作流执行引擎（本期仅编排，执行在后续迭代）
- 不实现节点间实时数据传递
- 不实现协作编辑
- 不改变现有页面

## Decisions

### 决策 1：画布库 — ReactFlow vs. React-Diagrams vs. 自研

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| ReactFlow (`@xyflow/react`) | 社区最活跃、TS 支持好、MIT 许可、内置拖拽/连线/小地图 | 体积 ~100KB | ✅ |
| React-Diagrams (Project Storm) | 功能丰富 | 不再维护、依赖老旧 | ❌ |
| 自研 SVG/Canvas | 无依赖、完全可控 | 开发量大、难以达到专业库的交互体验 | ❌ |

**选择 ReactFlow v12**：MIT 许可、React 18 兼容、API 简洁、内置 Dagre 布局。

### 决策 2：工作流存储格式

```json
{
  "id": "uuid",
  "name": "我的工作流",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "nodes": [
    {
      "id": "node-1",
      "type": "document_input",
      "position": { "x": 100, "y": 200 },
      "data": { "label": "PDF 输入", "file_type": ".pdf", "max_size_mb": 100 }
    }
  ],
  "edges": [
    { "id": "edge-1", "source": "node-1", "target": "node-2" }
  ]
}
```

存储为项目 `workflows/` 目录下的 JSON 文件。

### 决策 3：节点类型注册系统

预定义节点类型表（可扩展）：

| 类型 ID | 名称 | 颜色 | 配置项 |
|---------|------|------|--------|
| `document_input` | 文档输入 | blue | file_type, max_size |
| `text_splitter` | 文本分割 | green | chunk_size, chunk_overlap |
| `embedding` | 嵌入向量 | purple | model, dims |
| `retriever` | 检索器 | amber | top_k, mode (hybrid/vector/bm25) |
| `llm_answer` | LLM 回答 | rose | model, temperature, system_prompt |
| `output` | 输出 | gray | format (text/markdown/json) |

### 决策 4：前端组件结构

```
src/
  pages/
    WorkflowPage.jsx          # 页面主体（画布 + 侧边面板）
  components/workflow/
    WorkflowCanvas.jsx        # ReactFlow 画布包装
    WorkflowNode.jsx          # 自定义节点渲染
    NodeConfigPanel.jsx       # 侧边配置面板
    NodePalette.jsx           # 左侧节点拖拽面板
    WorkflowToolbar.jsx       # 顶部工具栏（保存/加载/新建）
    nodeTypes.js              # 节点类型注册表 + 配置表单组件
```

### 决策 5：后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workflows` | 列表所有工作流 |
| POST | `/api/workflows` | 创建新工作流 |
| GET | `/api/workflows/{id}` | 获取单个工作流 |
| PUT | `/api/workflows/{id}` | 更新工作流 |
| DELETE | `/api/workflows/{id}` | 删除工作流 |

## Risks / Trade-offs

- **[低风险] ReactFlow 版本兼容**：v12 需要 React 18+（项目已满足）
- **[低风险] 工作流文件存储**：文件存储简单但无并发控制 → 后续可升级为 DB 存储
- **[中风险] 拖拽连线 UX**：ReactFlow 的连线交互可能对新手不够直观 → 添加使用提示

## Open Questions

- 是否需要自动布局按钮（Dagre 算法）？→ 建议作为工具栏按钮提供
- 节点配置是否需要实时校验？→ 建议保存时做基础校验
