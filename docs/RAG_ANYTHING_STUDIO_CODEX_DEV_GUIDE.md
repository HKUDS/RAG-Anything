# RAG-Anything Studio 开发指导文档

## 0. 项目背景

本项目目标是为 `HKUDS/RAG-Anything` 增加一个专业的本地 Web GUI，暂定名称为：

> **RAG-Anything Studio**

RAG-Anything 是一个基于 LightRAG 的多模态文档 RAG 框架，面向包含文本、图片、表格、公式等复杂内容的文档处理与问答。官方仓库定位为“All-in-One Multimodal Document Processing RAG system built on LightRAG”。它的核心价值在于把多模态内容统一组织为可检索、可推理的知识结构。([GitHub](https://github.com/HKUDS/RAG-Anything?utm_source=chatgpt.com))

LightRAG 本身已有 Server / WebUI，用于文档索引、知识图谱探索和简单 RAG 查询，但 RAG-Anything 在多模态解析、content list、图片/表格/公式处理、VLM 增强查询等方面有更强的专门需求，因此本项目不应只是复刻 LightRAG WebUI，而应做成一个**多模态 RAG 处理链路可视化与调试工作台**。([GitHub](https://github.com/hkuds/lightrag?utm_source=chatgpt.com))

------

## 1. 产品定位

### 1.1 一句话定位

**RAG-Anything Studio 是一个面向 RAG-Anything 的本地优先 Web 工作台，用于可视化完成多模态文档上传、解析、content_list 检查、索引构建、问答查询和检索调试。**

### 1.2 不要做成什么

不要做成简单的 Chat UI。

不要一开始做 SaaS、多用户、权限系统、团队协作、计费系统、插件市场。

不要直接大规模魔改 LightRAG WebUI。

### 1.3 第一阶段目标

第一阶段只做本地开发者可用的 MVP：

```text
上传文档
→ 选择解析参数
→ 启动 RAG-Anything 处理任务
→ 查看任务状态和日志
→ 发起查询
→ 查看回答和来源
```

------

## 2. 设计原则

### 2.1 Local-first

默认在本地运行：

```bash
python -m raganything_studio
```

或者：

```bash
raganything-studio --host 127.0.0.1 --port 7860
```

### 2.2 不侵入核心库

尽量不要修改 RAG-Anything 核心逻辑。

优先通过 wrapper 调用已有 Python API。

如果确实需要新增 hook / callback，应保持最小 PR 形式。

### 2.3 任务异步化

文档解析和多模态处理可能很慢，尤其是 VLM caption、OCR、表格和公式处理。因此所有耗时任务必须走 job system。

前端不能阻塞等待 HTTP 请求完成。

### 2.4 可观测性优先

GUI 的最大价值不是“好看”，而是让用户知道：

```text
当前处理到了哪一步
解析出了哪些内容
图片、表格、公式是否成功处理
检索时命中了什么
回答依据来自哪里
失败原因是什么
```

------

## 3. 推荐技术栈

### 3.1 Backend

```text
FastAPI
Uvicorn
Pydantic
asyncio
SQLite
SQLModel 或 SQLAlchemy
python-multipart
```

第一阶段不要引入 Celery / Redis。

可以先使用：

```python
asyncio.create_task()
```

管理后台任务。

### 3.2 Frontend

```text
Vite
React
TypeScript
TailwindCSS
shadcn/ui
TanStack Query
Zustand
React Hook Form
PDF.js
KaTeX
Monaco Editor
```

第二阶段再考虑：

```text
React Flow
Cytoscape.js / Sigma.js
ECharts
```

------

## 4. 建议目录结构

优先把 Studio 做成独立模块，降低对主项目侵入。

```text
RAG-Anything/
├── raganything/
│   └── ...
├── raganything_studio/
│   ├── __init__.py
│   ├── __main__.py
│   ├── backend/
│   │   ├── app.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── documents.py
│   │   │   ├── jobs.py
│   │   │   ├── query.py
│   │   │   ├── settings.py
│   │   │   └── health.py
│   │   ├── core/
│   │   │   ├── job_manager.py
│   │   │   ├── storage.py
│   │   │   └── logging.py
│   │   ├── services/
│   │   │   ├── raganything_service.py
│   │   │   ├── document_service.py
│   │   │   ├── content_list_service.py
│   │   │   └── query_service.py
│   │   ├── schemas/
│   │   │   ├── document.py
│   │   │   ├── job.py
│   │   │   ├── query.py
│   │   │   └── settings.py
│   │   └── static/
│   │       └── frontend build output
│   └── frontend/
│       ├── package.json
│       ├── index.html
│       ├── src/
│       │   ├── main.tsx
│       │   ├── App.tsx
│       │   ├── api/
│       │   ├── pages/
│       │   ├── components/
│       │   ├── stores/
│       │   └── types/
│       └── vite.config.ts
├── docs/
│   └── RAG_ANYTHING_STUDIO_CODEX_DEV_GUIDE.md
└── README.md
```

------

## 5. 后端设计

## 5.1 FastAPI 入口

文件：

```text
raganything_studio/backend/app.py
```

职责：

```text
创建 FastAPI app
注册 router
配置 CORS
挂载前端静态文件
提供健康检查
```

建议结构：

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from raganything_studio.backend.api import documents, jobs, query, settings, health

def create_app() -> FastAPI:
    app = FastAPI(title="RAG-Anything Studio")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/health", tags=["health"])
    app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(query.router, prefix="/api/query", tags=["query"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])

    return app

app = create_app()
```

------

## 5.2 启动入口

文件：

```text
raganything_studio/__main__.py
```

职责：

```text
支持 python -m raganything_studio 启动
支持 host / port 参数
```

建议：

```python
import argparse
import uvicorn

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7860, type=int)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run(
        "raganything_studio.backend.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )

if __name__ == "__main__":
    main()
```

------

# 6. 数据模型

## 6.1 Document

```python
class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"

class DocumentRecord(BaseModel):
    id: str
    filename: str
    original_path: str
    working_dir: str
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
```

## 6.2 Job

```python
class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class JobStage(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    PARSING = "parsing"
    EXTRACTING_CONTENT = "extracting_content"
    PROCESSING_IMAGES = "processing_images"
    PROCESSING_TABLES = "processing_tables"
    PROCESSING_EQUATIONS = "processing_equations"
    BUILDING_INDEX = "building_index"
    FINALIZING = "finalizing"
    DONE = "done"
    FAILED = "failed"

class JobRecord(BaseModel):
    id: str
    document_id: str | None = None
    status: JobStatus
    stage: JobStage
    progress: float = 0.0
    message: str = ""
    logs: list[str] = []
    error: str | None = None
    created_at: datetime
    updated_at: datetime
```

## 6.3 ProcessOptions

```python
class ProcessOptions(BaseModel):
    parser: str = "mineru"
    parse_method: str = "auto"

    enable_image_processing: bool = True
    enable_table_processing: bool = True
    enable_equation_processing: bool = True

    lang: str = "ch"
    device: str = "cpu"

    start_page: int | None = None
    end_page: int | None = None

    output_dir: str | None = None
    working_dir: str | None = None
```

## 6.4 QueryRequest

```python
class QueryRequest(BaseModel):
    question: str
    mode: str = "hybrid"
    use_multimodal: bool = True
    top_k: int | None = None
```

## 6.5 QueryResponse

```python
class SourceItem(BaseModel):
    document_id: str | None = None
    filename: str | None = None
    page_idx: int | None = None
    type: str | None = None
    score: float | None = None
    preview: str | None = None
    raw: dict[str, Any] | None = None

class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = []
    raw: dict[str, Any] | None = None
```

------

# 7. API 设计

## 7.1 健康检查

```http
GET /api/health
```

返回：

```json
{
  "status": "ok",
  "app": "RAG-Anything Studio"
}
```

------

## 7.2 上传文档

```http
POST /api/documents/upload
Content-Type: multipart/form-data
```

表单字段：

```text
file: UploadFile
```

返回：

```json
{
  "document_id": "doc_xxx",
  "filename": "paper.pdf",
  "status": "uploaded"
}
```

要求：

```text
上传文件保存到 studio_data/uploads/{document_id}/original_filename
创建 document record
不在上传接口里直接处理文档
```

------

## 7.3 文档列表

```http
GET /api/documents
```

返回：

```json
{
  "items": [
    {
      "id": "doc_xxx",
      "filename": "paper.pdf",
      "status": "uploaded",
      "created_at": "..."
    }
  ]
}
```

------

## 7.4 启动处理任务

```http
POST /api/documents/{document_id}/process
```

请求：

```json
{
  "parser": "mineru",
  "parse_method": "auto",
  "enable_image_processing": true,
  "enable_table_processing": true,
  "enable_equation_processing": true,
  "lang": "ch",
  "device": "cpu"
}
```

返回：

```json
{
  "job_id": "job_xxx",
  "status": "queued"
}
```

要求：

```text
立即返回 job_id
后台异步执行
更新 job stage 和 logs
失败时保存 error traceback
```

------

## 7.5 查询任务状态

```http
GET /api/jobs/{job_id}
```

返回：

```json
{
  "id": "job_xxx",
  "status": "running",
  "stage": "processing_images",
  "progress": 0.4,
  "message": "Processing images...",
  "logs": [
    "[12:01:00] Started processing paper.pdf",
    "[12:01:10] Parser: mineru, parse_method: auto"
  ],
  "error": null
}
```

------

## 7.6 查询任务日志流

第一阶段可以先轮询 `GET /api/jobs/{job_id}`。

第二阶段实现：

```http
GET /api/jobs/{job_id}/stream
```

使用 SSE。

返回事件格式：

```text
event: log
data: {"message":"Parsing document..."}

event: progress
data: {"stage":"building_index","progress":0.8}
```

------

## 7.7 发起问答

```http
POST /api/query
```

请求：

```json
{
  "question": "What are the main findings in this paper?",
  "mode": "hybrid",
  "use_multimodal": true
}
```

返回：

```json
{
  "answer": "...",
  "sources": [],
  "raw": {}
}
```

第一阶段如果无法可靠抽取 sources，可以先返回空数组，但必须保留字段，方便后续增强。

------

## 7.8 获取 content_list

```http
GET /api/documents/{document_id}/content-list
```

返回：

```json
{
  "document_id": "doc_xxx",
  "items": [
    {
      "type": "text",
      "text": "...",
      "page_idx": 0
    },
    {
      "type": "image",
      "img_path": "...",
      "page_idx": 1
    },
    {
      "type": "table",
      "table_body": "...",
      "page_idx": 2
    },
    {
      "type": "equation",
      "latex": "...",
      "page_idx": 2
    }
  ]
}
```

这个接口第二阶段重点实现。

------

# 8. RAG-Anything 封装服务

文件：

```text
raganything_studio/backend/services/raganything_service.py
```

## 8.1 职责

```text
初始化 RAGAnything 实例
加载配置
执行 process_document_complete
执行 aquery
捕获日志和错误
```

## 8.2 注意事项

RAG-Anything 官方示例通常使用异步方式调用，例如处理文档和查询都可能是 async 风格。Codex 应优先适配 async 调用，不要在 async route 中直接阻塞长任务。([GitHub](https://github.com/HKUDS/RAG-Anything?utm_source=chatgpt.com))

伪代码：

```python
class RAGAnythingService:
    def __init__(self, settings: StudioSettings):
        self.settings = settings
        self._rag = None

    async def get_rag(self):
        if self._rag is None:
            self._rag = await self._create_rag()
        return self._rag

    async def process_document(
        self,
        document_path: str,
        options: ProcessOptions,
        log: Callable[[str], None],
        set_progress: Callable[[str, float, str], None],
    ) -> None:
        rag = await self.get_rag()

        set_progress("preparing", 0.05, "Preparing document processing")
        log(f"Processing document: {document_path}")
        log(f"Parser={options.parser}, parse_method={options.parse_method}")

        set_progress("parsing", 0.15, "Parsing document")

        # Prefer actual RAG-Anything API here.
        # Example shape:
        await rag.process_document_complete(
            file_path=document_path,
            output_dir=options.output_dir,
            parse_method=options.parse_method,
        )

        set_progress("done", 1.0, "Document processing completed")

    async def query(self, request: QueryRequest) -> QueryResponse:
        rag = await self.get_rag()

        result = await rag.aquery(
            request.question,
            mode=request.mode,
        )

        return QueryResponse(
            answer=str(result),
            sources=[],
            raw={"result": result},
        )
```

实际参数名必须以当前仓库代码为准。Codex 在实现时应先查找：

```text
RAGAnything
RAGAnythingConfig
process_document_complete
insert_content_list
aquery
```

并按真实函数签名改写。

------

# 9. Job Manager 设计

文件：

```text
raganything_studio/backend/core/job_manager.py
```

## 9.1 目标

第一阶段实现进程内 job manager。

```python
class JobManager:
    def create_job(self, document_id: str | None = None) -> JobRecord:
        ...

    def get_job(self, job_id: str) -> JobRecord:
        ...

    def append_log(self, job_id: str, message: str) -> None:
        ...

    def update_progress(
        self,
        job_id: str,
        stage: JobStage,
        progress: float,
        message: str,
    ) -> None:
        ...

    def mark_failed(self, job_id: str, error: str) -> None:
        ...

    def mark_succeeded(self, job_id: str) -> None:
        ...
```

## 9.2 第一阶段存储

可以先使用内存字典：

```python
self.jobs: dict[str, JobRecord] = {}
```

但代码结构要预留替换为 SQLite 的能力。

------

# 10. 前端页面设计

## 10.1 页面列表

第一阶段只做以下页面：

```text
/
Dashboard

/documents
Document list

/documents/new
Upload and process document

/jobs/:jobId
Job detail and logs

/query
Query console

/settings
Settings page
```

------

## 10.2 Dashboard

显示：

```text
RAG-Anything Studio
Local multimodal RAG workspace

Cards:
- Documents
- Running jobs
- Indexed documents
- Last error

Primary buttons:
- Upload Document
- Query Knowledge Base
```

------

## 10.3 Upload 页面

组件：

```text
FileUploadCard
ProcessOptionsForm
StartProcessButton
```

表单字段：

```text
Parser:
- mineru
- docling
- paddleocr

Parse method:
- auto
- ocr
- txt

Modal processing:
[x] Image
[x] Table
[x] Equation

Language:
- ch
- en

Device:
- cpu
- cuda
- cuda:0
- mps
```

交互流程：

```text
用户选择文件
点击 Upload
后端返回 document_id
用户选择处理参数
点击 Process
后端返回 job_id
跳转 /jobs/{job_id}
```

------

## 10.4 Job 页面

显示：

```text
Job status badge
Progress bar
Current stage
Current message
Log console
Error panel if failed
Button: Go to Query when succeeded
```

日志区域样式类似终端：

```text
[12:00:01] Upload complete
[12:00:05] Started processing
[12:00:20] Parsing document
[12:01:30] Building index
[12:02:10] Done
```

第一阶段使用轮询：

```typescript
useQuery({
  queryKey: ["job", jobId],
  queryFn: () => getJob(jobId),
  refetchInterval: 1000,
});
```

------

## 10.5 Query 页面

布局：

```text
左侧：Query form
右侧：Answer panel
下方：Sources panel / Raw result panel
```

字段：

```text
Question textarea
Mode select:
- naive
- local
- global
- hybrid
- mix

Use multimodal toggle
Submit button
```

回答显示：

```text
Markdown answer
Sources list
Raw JSON collapsible panel
```

------

## 10.6 Settings 页面

第一阶段可以先做 UI，不一定完全接入。

字段：

```text
Working directory
Output directory

LLM provider
LLM model
LLM base URL
LLM API key

Embedding provider
Embedding model
Embedding base URL
Embedding API key

Vision model provider
Vision model
Vision base URL
Vision API key
```

按钮：

```text
Save settings
Test LLM
Test Embedding
Test Vision Model
```

------

# 11. 第二阶段重点：Content List Inspector

RAG-Anything 支持把内容组织为 text、image、table、equation 等多模态 content list，并支持通过 `insert_content_list()` 直接插入预解析内容。GUI 应该把这个能力可视化。([GitHub](https://github.com/HKUDS/RAG-Anything?utm_source=chatgpt.com))

## 11.1 页面

```text
/documents/:documentId/content
```

## 11.2 UI

左侧：

```text
Page 1
  Text block 1
  Image 1
  Table 1

Page 2
  Equation 1
  Text block 2
```

右侧：

根据类型渲染：

```text
text       -> markdown/text preview
image      -> image preview + metadata
table      -> markdown table preview + raw markdown
equation   -> KaTeX rendered formula + raw LaTeX
generic    -> JSON viewer
```

## 11.3 价值

这个页面是 RAG-Anything Studio 区别于普通 WebUI 的核心功能。

------

# 12. 第三阶段重点：Retrieval Trace

目标：每次 query 后展示检索链路。

```text
Question
→ Query mode
→ Retrieved text chunks
→ Retrieved images
→ Retrieved tables
→ Retrieved equations
→ Graph entities
→ Final context
→ Answer
```

如果当前 RAG-Anything API 无法直接返回 trace，先保留接口字段：

```json
{
  "answer": "...",
  "sources": [],
  "trace": {
    "retrieved_text": [],
    "retrieved_images": [],
    "retrieved_tables": [],
    "retrieved_equations": [],
    "graph_entities": [],
    "context": ""
  }
}
```

后续再接入真实 trace。

------

# 13. 第四阶段重点：Knowledge Graph 可视化

LightRAG 的核心思想之一是图结构与向量表示结合，用双层检索提升复杂信息获取能力。RAG-Anything 进一步把多模态内容作为互联知识实体处理。([arXiv](https://arxiv.org/abs/2410.05779?utm_source=chatgpt.com))

Studio 的 KG 页面建议设计为：

```text
/graph
```

节点类型：

```text
Document
Page
Text
Image
Table
Equation
Entity
CustomModalEntity
```

边类型：

```text
belongs_to
mentions
same_page_as
caption_of
describes
related_to
derived_from
```

第一阶段不要做。第二或第三阶段再做。

------

# 14. 开发任务拆分

## Milestone 1：Backend MVP

目标：后端可启动，基础 API 可用。

任务：

```text
1. 创建 raganything_studio 包
2. 创建 FastAPI app
3. 实现 /api/health
4. 实现文件上传
5. 实现 DocumentRecord 内存存储
6. 实现 JobManager 内存存储
7. 实现启动处理任务接口
8. 封装 RAGAnythingService
9. 实现 /api/query
10. 添加基础错误处理
```

验收标准：

```text
python -m raganything_studio --reload 可以启动
GET /api/health 返回 ok
POST /api/documents/upload 能保存文件
POST /api/documents/{id}/process 能返回 job_id
GET /api/jobs/{id} 能看到状态和日志
POST /api/query 能调用 RAG-Anything 查询
```

------

## Milestone 2：Frontend MVP

目标：前端能完成上传、处理、查询。

任务：

```text
1. 创建 Vite React TS 项目
2. 配置 Tailwind
3. 创建 API client
4. 创建 Dashboard
5. 创建 Document Upload 页面
6. 创建 Job Detail 页面
7. 创建 Query 页面
8. 创建 Settings 页面占位
```

验收标准：

```text
npm run dev 可启动
前端能上传文件
前端能启动处理任务
前端能查看 job 状态和日志
前端能发起 query 并显示 answer
```

------

## Milestone 3：打包和集成

目标：前后端可一起运行。

任务：

```text
1. 前端 build 输出到 backend/static
2. FastAPI 挂载静态文件
3. python -m raganything_studio 启动后可直接访问 WebUI
4. 添加 README 使用说明
```

验收标准：

```text
运行 python -m raganything_studio
浏览器访问 http://127.0.0.1:7860
可以看到 Studio UI
可以完成基本上传、处理、查询流程
```

------

## Milestone 4：Content List Inspector

任务：

```text
1. 后端实现读取 content_list 输出
2. 标准化 content_list item schema
3. 前端实现 content list 页面
4. 支持 text/image/table/equation 渲染
5. 支持按 page_idx 分组
```

验收标准：

```text
处理完成的文档可以打开 content list 页面
能看到文本块、图片、表格、公式
图片可预览
表格可 markdown 渲染
公式可 KaTeX 渲染
```

------

# 15. 错误处理要求

所有后端 API 都应返回清晰错误。

示例：

```json
{
  "detail": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document doc_xxx was not found"
  }
}
```

常见错误码：

```text
DOCUMENT_NOT_FOUND
JOB_NOT_FOUND
UPLOAD_FAILED
PROCESS_FAILED
QUERY_FAILED
INVALID_PROCESS_OPTIONS
RAG_INIT_FAILED
SETTINGS_INVALID
```

Job 失败时必须保存 traceback，但前端默认只展示简短错误，提供展开详情按钮。

------

# 16. 日志要求

Job 日志格式：

```text
[HH:MM:SS] message
```

示例：

```text
[12:00:01] Created job job_abc
[12:00:02] Processing document paper.pdf
[12:00:02] Parser=mineru, parse_method=auto
[12:00:03] Initializing RAG-Anything
[12:00:08] Started process_document_complete
[12:02:21] Document processing completed
```

------

# 17. 环境检查功能

后续应加入：

```http
GET /api/settings/environment
```

返回：

```json
{
  "python": "3.11.8",
  "raganything_installed": true,
  "lightrag_installed": true,
  "mineru_available": true,
  "libreoffice_available": false,
  "cuda_available": false
}
```

前端显示：

```text
Environment Check
- Python
- RAG-Anything
- LightRAG
- MinerU
- LibreOffice
- CUDA
```

Office 文档处理通常依赖 LibreOffice，因此这个检查很重要。RAG-Anything README 也提示 Office 文档处理需要安装 LibreOffice。([GitHub](https://github.com/HKUDS/RAG-Anything?utm_source=chatgpt.com))

------

# 18. Codex 实现注意事项

## 18.1 先读源码再写 wrapper

在实现 `RAGAnythingService` 前，先全局搜索：

```bash
grep -R "class RAGAnything" -n .
grep -R "def process_document_complete" -n .
grep -R "async def process_document_complete" -n .
grep -R "def aquery" -n .
grep -R "insert_content_list" -n .
```

以真实函数签名为准。

## 18.2 不要硬编码 API Key

Settings 第一阶段可以读取 `.env`。

不要把 API key 写死到前端。

## 18.3 后端不要直接信任上传文件名

保存文件时使用安全文件名。

建议：

```python
from pathlib import Path
from uuid import uuid4

document_id = f"doc_{uuid4().hex}"
safe_name = Path(upload.filename).name
```

## 18.4 大文件上传

第一阶段不做分片上传。

但要预留错误提示：

```text
File too large
Unsupported file type
Upload failed
```

## 18.5 前端不要假设任务一定成功

Job 页面必须处理：

```text
queued
running
succeeded
failed
cancelled
```

------

# 19. MVP 验收 Checklist

完成后应满足：

```text
[ ] python -m raganything_studio 可启动
[ ] /api/health 正常
[ ] 前端首页可访问
[ ] 可以上传 PDF
[ ] 可以选择 parser 和 parse_method
[ ] 可以启动处理任务
[ ] 可以看到 job 状态
[ ] 可以看到 job 日志
[ ] 处理失败时能看到错误
[ ] 处理成功后可以进入 query 页面
[ ] 可以提交问题
[ ] 可以显示回答
[ ] README 有启动说明
```

------

# 20. README 初稿结构

新增一个 README section：

~~~markdown
## RAG-Anything Studio

RAG-Anything Studio is a local-first Web workspace for visualizing and debugging the multimodal RAG pipeline of RAG-Anything.

### Features

- Document upload and parser configuration
- Async processing jobs with live logs
- Query console for multimodal RAG
- Content list inspector for text, images, tables, and equations
- Retrieval trace and source preview

### Quick Start

```bash
pip install -e .
python -m raganything_studio --host 127.0.0.1 --port 7860
~~~

Open:

~~~text
http://127.0.0.1:7860
---

# 21. 最终开发策略

Codex 应按以下优先级实现：

```text
第一优先级：
后端 API 跑通

第二优先级：
前端上传、任务、查询闭环跑通

第三优先级：
content_list inspector

第四优先级：
retrieval trace

第五优先级：
graph visualization
~~~

不要在第一版中实现复杂权限、登录、多用户、云部署、插件市场。

本项目的核心不是“做一个漂亮网页”，而是：

> 把 RAG-Anything 的多模态文档处理链路从黑盒变成可观察、可调试、可展示的工程系统。