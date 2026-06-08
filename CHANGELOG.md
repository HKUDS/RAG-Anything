# RAG-Anything 改动记录

> 本文档记录基于 [HKUDS/RAG-Anything](https://github.com/HKUDS/RAG-Anything) 主线的所有自定义改动。

---

## 一、修改的原项目文件（4 个，+82 / -3 行）

### 1.1 `raganything/__init__.py` [+29 行]

**改动内容：** 新增 chunking 模块的公开导出

```python
# 新增 chunking 策略的可选导入
from .chunking import (
    recursive_chunking, sentence_chunking, structure_chunking,
    make_semantic_chunking, make_agentic_chunking,
    build_chunking_func, STRATEGY_META,
)
```

**原因：** 使 6 种分块策略成为 `raganything` 包的公开 API，用户可直接 `from raganything import recursive_chunking`。

---

### 1.2 `raganything/parser.py` [+20 行]

**改动 1：Windows LibreOffice 路径自动检测**

```python
if _IS_WINDOWS:
    for lo_path in reversed([
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]):
        if os.path.exists(lo_path):
            commands_to_try.insert(0, lo_path)
```

**原因：** LibreOffice 在 Windows 上不会自动加入 PATH 环境变量，导致 `convert_office_to_pdf()` 找不到 `soffice` 命令。新增自动检测常见安装路径，64 位优先于 32 位。

**改动 2：DoclingParser 支持 .doc 旧格式**

```python
if doc_path.suffix.lower() == ".doc":
    pdf_path = self.convert_office_to_pdf(doc_path, output_dir)
    return self.parse_pdf(pdf_path=pdf_path, output_dir=output_dir, lang=lang, **kwargs)
```

**原因：** Docling 原生不支持旧版 `.doc`（二进制）格式，新增自动通过 LibreOffice 转换为 PDF 后解析。

---

### 1.3 `raganything/query.py` [+32 / -2 行]

**改动内容：** `aquery()` 方法新增流式查询支持

```python
stream = kwargs.pop("stream", False)         # 新增 stream 参数
if stream and vlm_enhanced:                  # VLM 与流式不兼容
    vlm_enhanced = False
if stream:
    if isinstance(result, str):              # 降级处理
        return result                        # 非流式返回
    return result                            # 返回 AsyncIterator
```

**修复的 Bug：**
- 流式返回后死代码（完成日志和回调永不触发）→ 重构控制流
- VLM+流式互斥时仅 `info` 日志 → 提升为 `warning`
- 返回类型注解 `-> str` 与实际不符 → 移除不准确注解
- 中文错误消息与项目风格不一致 → 改为英文

---

### 1.4 `raganything/utils.py` [+1 / -1 行]

**改动内容：** 类型注解修复

```python
# 修复前
multimodal_content: list[dict[str, any]] | None = None
# 修复后
multimodal_content: list[dict[str, Any]] | None = None
```

---

## 二、新增后端文件（8 个，~3,400 行）

### 2.1 `server.py`（1,649 行）

**完整的 FastAPI Web 服务器**，提供 30+ 个 REST API 端点：

| 类别 | 端点 | 方法 | 说明 |
|------|------|------|------|
| 上传 | `/api/upload` | POST | 单文件异步上传 |
| | `/api/upload/batch` | POST | 批量多文件上传 |
| | `/api/upload/folder` | POST | 文件夹批量处理 |
| | `/api/upload/content` | POST | 文本粘贴入库 |
| | `/api/upload/url` | POST | URL 远程导入 |
| 知识库 | `/api/knowledge/documents` | GET | 文档列表 |
| | `/api/knowledge/documents/{id}` | DELETE | 单文档删除 |
| | `/api/knowledge/documents/batch-delete` | POST | 批量删除文档 |
| | `/api/knowledge/stats` | GET | 统计信息 |
| | `/api/knowledge/entities` | GET | 实体列表 |
| | `/api/knowledge/graph` | GET | 知识图谱数据 |
| 查询 | `/api/query` | POST | 普通查询（6 种模式） |
| | `/api/query/stream` | POST | SSE 流式查询 |
| | `/api/query/history` | GET / DELETE | 查询历史管理 |
| KB管理 | `/api/kb/list` | GET | 知识库列表 |
| | `/api/kb/create` | POST | 创建知识库 |
| | `/api/kb/switch` | PUT | 切换活跃知识库 |
| | `/api/kb/{name}` | DELETE | 删除知识库 |
| 智能体 | `/api/agents` | GET/POST | 智能体列表/创建 |
| | `/api/agents/{id}` | PUT/DELETE | 更新/删除智能体 |
| | `/api/agents/{id}/conversations` | GET/POST | 对话线程管理 |
| | `/api/agents/{id}/conversations/{tid}` | PUT/DELETE | 重命名/删除对话 |
| | `/api/agents/{id}/query/stream` | POST | 智能体流式查询(SSE) |
| | `/api/agents/templates` | GET | 预设模板 |
| 设置 | `/api/settings` | GET/PUT | 系统配置 |
| 监控 | `/api/monitor/status` | GET | 任务状态 |
| | `/api/monitor/stats` | GET | LLM 统计 |
| | `/api/monitor/logs` | GET | 事件日志 |
| 其他 | `/api/health` | GET | 健康检查 |
| | `/ws` | WS | WebSocket 实时推送 |

**关键特性：** 后台异步处理（BackgroundTasks + 子进程隔离）、WebSocket 实时推送处理进度、多知识库实例缓存与管理、Worker 错误传播检测。

---

### 2.2 `agent_manager.py`（310 行）

**智能体管理器**，提供：

- 智能体 CRUD 操作（创建/读取/更新/删除）
- 对话线程管理（创建/列表/重命名/删除）
- JSON 持久化存储（`agent_meta.json`）
- 预设模板加载（`agent_templates.json`）

---

### 2.3 `process_worker.py`（295 行）

**独立文件处理 Worker**，子进程中运行，彻底隔离 LightRAG 实例：

- 支持多 KB 目录隔离（`--kb` 参数）
- 支持 6 种分块策略热切换（`--strategy` 参数）
- 纯文本文件直接读取处理
- 复杂文件（PDF/DOCX 等）通过 RAGAnything 解析
- **VLM OCR 兜底**：当 Docling 解析失败或 chunks=0 时，自动调用千问 VL 模型做 OCR
- **错误传播机制**：合并阶段失败时 `sys.exit(1)`，确保 server 能检测到错误

---

### 2.4 `raganything/chunking.py`（770 行）

**6 种文本分块策略**：

| 策略 | 函数 | 费用 | 说明 |
|------|------|------|------|
| 固定大小切割 | *(LightRAG 内置)* | 🟢 免费 | 按 token 数固定切割，重叠窗口 |
| 递归字符分割 | `recursive_chunking` | 🟢 免费 | 段落→句子→字符，逐级尝试自然边界 |
| 句子级语义分割 | `sentence_chunking` | 🟢 免费 | 精确识别句边界，保证句子完整性 |
| 文档结构感知 | `structure_chunking` | 🟢 免费 | 按标题/章节结构切分，保留文档逻辑 |
| 语义相似度分块 | `make_semantic_chunking(embed_fn)` | 🟡 中等 | 基于 Embedding 相似度，在语义边界处切割 |
| LLM 智能分块 | `make_agentic_chunking(llm_fn)` | 🔴 较高 | LLM 自主判断最佳分割点 |

**修复的 Bug：**
- `lightrag.operate.chunking_by_token_size` 动态导入可能崩溃 → 移到顶部 try/except 保护
- recursive 分块中 `tokenizer.encode` 双重调用 → 缓存 token 计数
- Agentic 分块静默截断 500 行后内容 → 显式 warning + 告知丢失行数
- Agentic 分块分隔符与其他策略不一致 → 统一为 `"\n\n"`

---

### 2.5 `query.py`（96 行）

独立的命令行查询工具脚本。

---

### 2.6 `upload_and_query.py`（168 行）

独立的命令行上传+查询一体脚本。

---

### 2.7 `agent_meta.json`（67 行）

智能体元数据持久化存储。

---

### 2.8 `agent_templates.json`（68 行）

5 个预设智能体模板定义。

---

## 三、新增前端文件（10 个源文件，~2,200 行）

### 技术栈

- **React 18** + React Router 6（SPA 路由）
- **Vite 5**（构建工具，HMR 热更新）
- **Tailwind CSS 3**（样式框架，暗色主题）
- **Framer Motion**（页面过渡动画）
- **D3.js**（知识图谱力导向图）
- **Recharts**（统计图表）
- **Lucide React**（图标库）

### 源文件清单

| 文件 | 行数 | 功能 |
|------|------|------|
| `frontend/src/App.jsx` | 166 | 主布局：侧边栏导航 + 知识库选择器 + Toast 通知 |
| `frontend/src/main.jsx` | 13 | React 入口，挂载 BrowserRouter |
| `frontend/src/index.css` | 30 | Tailwind 基础样式 + 自定义组件类 |
| `frontend/src/utils/api.js` | 89 | 全量 API 调用封装（20+ 方法） |
| `frontend/src/pages/UploadPage.jsx` | 251 | 拖拽上传 + URL/粘贴/文件夹 + 分块策略选择 + **一键全部上传** |
| `frontend/src/pages/KnowledgePage.jsx` | 470 | 文档表格 + D3 知识图谱 + 实体列表 + **多选批量删除** |
| `frontend/src/pages/QueryPage.jsx` | 359 | 文本查询 + 6 种模式 + SSE 流式 + VLM + 查询历史 |
| `frontend/src/pages/AgentsPage.jsx` | 339 | 智能体管理：创建/编辑/删除 |
| `frontend/src/pages/AgentChatPage.jsx` | 458 | 智能体对话：SSE 流式 + 上下文检索过程展示 |
| `frontend/src/pages/SettingsPage.jsx` | 186 | 解析器/模型/分块策略等配置表单 |
| `frontend/src/pages/MonitorPage.jsx` | 100 | 任务队列 + LLM 调用统计 + 事件日志 |

### 配置文件

| 文件 | 说明 |
|------|------|
| `frontend/package.json` | NPM 依赖与脚本 |
| `frontend/vite.config.js` | Vite 配置（端口 5173，/api 代理到 8001） |
| `frontend/tailwind.config.js` | Tailwind 暗色主题配置 |
| `frontend/postcss.config.js` | PostCSS 配置 |
| `frontend/index.html` | HTML 入口（暗色 `<html class="dark">`） |

---

## 四、其他新增文件

| 文件 | 说明 |
|------|------|
| `docs/architecture.md` | 项目架构设计文档 |
| `rag_storage_kb_meta.json` | 多知识库元数据 |
| `query_history.json` | 查询历史持久化 |
| `agent_conversations/` | 智能体对话数据目录 |

---

## 五、总体统计

| 类别 | 数量 |
|------|------|
| 修改的原文件 | **4** 个 |
| 修改行数 | **+82 / -3** 行 |
| 新增后端源文件 | **8** 个（~3,400 行） |
| 新增前端源文件 | **10** 个（~2,200 行） |
| 新增 API 端点 | **30+** 个 |
| 新增前端路由 | **7** 个 |
| 新增分块策略 | **5** 种 |
| **总计新增代码** | **~5,700 行** |

---

## 六、变更时间线

| 日期 | 变更 |
|------|------|
| 2026-06-03 | 初始 fork，基础服务搭建 |
| 2026-06-04 | 前端框架搭建，智能体系统实现 |
| 2026-06-05 | 代码审查修复（流式死代码/Worker错误传播/VDB索引/类型注解）；chunking模块完善；批量操作功能（批量上传/批量删除/清空历史） |
