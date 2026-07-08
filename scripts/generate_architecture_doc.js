// RAG-Anything 系统架构文档生成器
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat,
  TableOfContents, HeadingLevel, BorderStyle, WidthType, ShadingType,
  PageNumber, PageBreak
} = require("docx");

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cm = { top: 80, bottom: 80, left: 120, right: 120 };
const hdrShade = { fill: "1B3A5C", type: ShadingType.CLEAR };
const altShade = { fill: "F2F7FB", type: ShadingType.CLEAR };

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text, font: "Arial", size: 32, bold: true, color: "1B3A5C" })],
    spacing: { before: 360, after: 240 },
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text, font: "Arial", size: 28, bold: true, color: "2B579A" })],
    spacing: { before: 280, after: 180 },
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    children: [new TextRun({ text, font: "Arial", size: 24, bold: true, color: "3A6DB5" })],
    spacing: { before: 200, after: 120 },
  });
}
function p(text) {
  return new Paragraph({
    spacing: { after: 120, line: 360 },
    children: [new TextRun({ text, font: "Arial", size: 21 })],
  });
}
function bp(label, text) {
  return new Paragraph({
    spacing: { after: 120, line: 360 },
    children: [
      new TextRun({ text: label, font: "Arial", size: 21, bold: true }),
      new TextRun({ text, font: "Arial", size: 21 }),
    ],
  });
}
function cblock(text) {
  return new Paragraph({
    spacing: { before: 40, after: 40, line: 280 },
    indent: { left: 360 },
    shading: { fill: "F5F5F5", type: ShadingType.CLEAR },
    children: [new TextRun({ text, font: "Consolas", size: 18, color: "333333" })],
  });
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 60, line: 340 },
    children: [new TextRun({ text, font: "Arial", size: 21 })],
  });
}
function hcell(text, w) {
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA }, shading: hdrShade, margins: cm,
    children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 20, bold: true, color: "FFFFFF" })] })],
  });
}
function cell(text, w, shade) {
  const o = { borders, width: { size: w, type: WidthType.DXA }, margins: cm,
    children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 20 })] })] };
  if (shade) o.shading = shade;
  return new TableCell(o);
}
function row(cells) { return new TableRow({ children: cells }); }
function tbl(w, cw, rows) {
  const t = new Table({ width: { size: w, type: WidthType.DXA }, columnWidths: cw, rows });
  // inject shading to data rows (skip header row)
  for (let i = 1; i < rows.length; i++) {
    for (const c of rows[i].cells || []) {
      if (!c.shading) c.shading = altShade;
    }
  }
  return t;
}
function brk() { return new Paragraph({ children: [new PageBreak()] }); }

// ── 预定义表格 ─────────────────────────────────────
const TBL_W = 9360;

// 后端技术栈表
const backendTable = tbl(TBL_W, [2800, 6560], [
  row([hcell("组件 (Component)", 2800), hcell("技术选型 (Technology)", 6560)]),
  row([cell("运行时", 2800), cell("Python 3.10+", 6560)]),
  row([cell("Web 框架", 2800), cell("FastAPI + Uvicorn", 6560)]),
  row([cell("RAG 引擎", 2800), cell("LightRAG (HKU) < 1.5", 6560)]),
  row([cell("文档解析", 2800), cell("MinerU, Docling, PaddleOCR, Marker, LibreOffice", 6560)]),
  row([cell("多模态处理", 2800), cell("Pillow, reportlab, WeasyPrint, Pygments", 6560)]),
  row([cell("LLM 集成", 2800), cell("OpenAI-compatible API (Qwen, DeepSeek, Minimax, vLLM, Ollama, LMStudio)", 6560)]),
  row([cell("嵌入模型", 2800), cell("OpenAI-compatible Embedding API", 6560)]),
  row([cell("认证与权限", 2800), cell("JWT (PyJWT) + bcrypt (passlib) + RBAC", 6560)]),
  row([cell("任务队列", 2800), cell("asyncio + BackgroundTasks", 6560)]),
  row([cell("监控", 2800), cell("Prometheus (prometheus_fastapi_instrumentator)", 6560)]),
  row([cell("限流", 2800), cell("slowapi (基于 IP)", 6560)]),
  row([cell("日志", 2800), cell("Python logging + RotatingFileHandler", 6560)]),
]);

// 前端技术栈表
const frontendTable = tbl(TBL_W, [2800, 6560], [
  row([hcell("组件", 2800), hcell("技术选型", 6560)]),
  row([cell("框架", 2800), cell("React 18 + Vite 5", 6560)]),
  row([cell("路由", 2800), cell("React Router v6 (懒加载)", 6560)]),
  row([cell("UI 设计", 2800), cell("Tailwind CSS 3", 6560)]),
  row([cell("动画", 2800), cell("Framer Motion", 6560)]),
  row([cell("图标", 2800), cell("Lucide React", 6560)]),
  row([cell("知识图谱", 2800), cell("D3.js v7", 6560)]),
  row([cell("工作流编辑器", 2800), cell("xyflow (React Flow) v12", 6560)]),
  row([cell("Markdown 渲染", 2800), cell("react-markdown + rehype-raw", 6560)]),
  row([cell("图表", 2800), cell("Recharts", 6560)]),
  row([cell("状态管理", 2800), cell("React Context (AuthContext)", 6560)]),
]);

// 数据层表
const dataLayerTable = tbl(TBL_W, [2800, 6560], [
  row([hcell("存储类型", 2800), hcell("技术/用途", 6560)]),
  row([cell("主数据库", 2800), cell("PostgreSQL (强制，无 SQLite 降级)", 6560)]),
  row([cell("矢量存储", 2800), cell("LightRAG PGVector (HNSW 索引)", 6560)]),
  row([cell("图存储", 2800), cell("LightRAG PG Graph Storage (实体/关系)", 6560)]),
  row([cell("文档状态", 2800), cell("LightRAG PGDocStatusStorage", 6560)]),
  row([cell("KV 存储", 2800), cell("LightRAG PGKVStorage (JSONB)", 6560)]),
  row([cell("认证数据库", 2800), cell("PostgreSQL (auth schema)", 6560)]),
  row([cell("文件存储", 2800), cell("本地文件系统 (working_dir)", 6560)]),
]);

// 模块组织表
const moduleTable = tbl(TBL_W, [2800, 6560], [
  row([hcell("模块", 2800), hcell("说明", 6560)]),
  row([cell("raganything/", 2800), cell("核心库：RAGAnything、Config、Parser、嵌入、分块策略", 6560)]),
  row([cell("raganything/parser/", 2800), cell("文档解析器：MineruParser、PDF、Office、Markdown、Image", 6560)]),
  row([cell("raganything/processor/", 2800), cell("处理混入：DocProcessor、ChunkProcessor、EmbedProcessor、MultimodalProcessor", 6560)]),
  row([cell("raganything/modalprocessors/", 2800), cell("多模态处理器：Image、Table、Equation、Generic、Context", 6560)]),
  row([cell("raganything/query/", 2800), cell("查询管线：QueryMixin、RRF融合、Graph查询、VLM增强", 6560)]),
  row([cell("raganything/hybrid_search/", 2800), cell("混合检索引擎：BM25+Vector+Graph RRF", 6560)]),
  row([cell("raganything/graph_rag/", 2800), cell("图检索：GraphRetriever、实体匹配、邻居遍历", 6560)]),
  row([cell("raganything/agentic_rag/", 2800), cell("Agentic RAG：ReAct/CoT引擎、工具注册、流式输出", 6560)]),
  row([cell("raganything/chunking/", 2800), cell("分块策略：recursive、sentence、structure、semantic、agentic", 6560)]),
  row([cell("raganything/routers/", 2800), cell("API 路由：auth、knowledge、agent、admin、autorepair", 6560)]),
  row([cell("raganything/services/", 2800), cell("服务层：auth、kb、ws、state、agent、graph-edit、prompt", 6560)]),
  row([cell("raganything/embedding/", 2800), cell("嵌入：Doubao Vision、ImageVectorRepo、EmbeddingCache", 6560)]),
  row([cell("raganything/video_processor/", 2800), cell("视频：FrameExtractor、AudioTranscriber、SceneDetector", 6560)]),
  row([cell("raganything/autorepair/", 2800), cell("汽修智能助手：知识图谱、知识管线、代理、部署", 6560)]),
  row([cell("frontend/src/", 2800), cell("React 前端：pages、components、context、hooks、utils", 6560)]),
]);

// 路由表
const routerTable = tbl(TBL_W, [2200, 1800, 5360], [
  row([hcell("路由模块", 2200), hcell("前缀", 1800), hcell("主要端点", 5360)]),
  row([cell("auth.py", 2200), cell("/api/auth", 1800), cell("注册、登录、Token刷新、密码修改、用户管理、角色管理、审计日志", 5360)]),
  row([cell("knowledge.py", 2200), cell("/api/upload, /api/knowledge, /api/kb, /api/files", 1800), cell("文件上传、解析、分块、嵌入、KB管理、文档列表、图片服务", 5360)]),
  row([cell("agent.py", 2200), cell("/api/agents", 1800), cell("智能体CRUD、对话管理、流式查询、历史记录、答案编辑", 5360)]),
  row([cell("admin.py", 2200), cell("/api/settings, /api/monitor, /api/workflows, /api/autorepair", 1800), cell("系统设置、监控、健康检查、工作流执行、AutoRepair专项", 5360)]),
]);

// 解析器表
const parserTable = tbl(TBL_W, [2200, 7160], [
  row([hcell("解析器", 2200), hcell("支持格式", 7160)]),
  row([cell("MinerU", 2200), cell("PDF, DOCX, PPTX, XLSX, Images, 扫描件 PDF (默认)", 7160)]),
  row([cell("Docling", 2200), cell("PDF, DOCX, PPTX (IBM 开源)", 7160)]),
  row([cell("PaddleOCR", 2200), cell("扫描件 PDF, 图片 OCR (百度)", 7160)]),
  row([cell("Marker", 2200), cell("PDF (高质量 Markdown 转换)", 7160)]),
  row([cell("LibreOffice", 2200), cell("DOC, RTF, ODT 等旧格式办公文档", 7160)]),
]);

// 分块策略表
const chunkTable = tbl(TBL_W, [2000, 2400, 4960], [
  row([hcell("策略", 2000), hcell("成本", 2400), hcell("说明", 4960)]),
  row([cell("fixed_size", 2000), cell("零成本", 2400), cell("固定大小切分，LightRAG 内置策略，默认方案", 4960)]),
  row([cell("recursive", 2000), cell("零成本", 2400), cell("递归字符分割：段落→句子→字符，支持重叠", 4960)]),
  row([cell("sentence", 2000), cell("零成本", 2400), cell("基于 jieba 的句子语义分割", 4960)]),
  row([cell("structure", 2000), cell("零成本", 2400), cell("文档结构感知分割（标题/段落）", 4960)]),
  row([cell("semantic", 2000), cell("中等成本", 2400), cell("基于嵌入相似度的语义分块，需要 Embedding API", 4960)]),
  row([cell("agentic", 2000), cell("较高成本", 2400), cell("LLM 驱动的智能分块，需要 LLM API", 4960)]),
]);

// 工作流节点表
const workflowTable = tbl(TBL_W, [2000, 7360], [
  row([hcell("节点类型", 2000), hcell("功能", 7360)]),
  row([cell("parse", 2000), cell("文档解析节点，将上传文件解析为 Markdown", 7360)]),
  row([cell("chunk", 2000), cell("分块节点，应用分块策略", 7360)]),
  row([cell("embed", 2000), cell("嵌入节点，将文本块转换为向量", 7360)]),
  row([cell("graph", 2000), cell("图谱节点，提取实体/关系构建知识图谱", 7360)]),
  row([cell("query", 2000), cell("查询节点，执行 RAG 查询", 7360)]),
  row([cell("multimodal", 2000), cell("多模态处理节点，处理图片/表格/视频", 7360)]),
]);

// 前端页面表
const pagesTable = tbl(TBL_W, [2800, 6560], [
  row([hcell("页面", 2800), hcell("功能", 6560)]),
  row([cell("LoginPage / RegisterPage", 2800), cell("用户登录与注册", 6560)]),
  row([cell("KnowledgePage", 2800), cell("知识库列表与管理（创建/删除/配置 KB）", 6560)]),
  row([cell("KnowledgeDetailPage", 2800), cell("单个知识库详情：文档列表、上传、图谱、查询、分块详情", 6560)]),
  row([cell("AgentsPage", 2800), cell("智能体列表与管理", 6560)]),
  row([cell("AgentChatPage", 2800), cell("智能体对话界面，支持流式输出、答案编辑", 6560)]),
  row([cell("WorkflowPage", 2800), cell("工作流可视化编辑与执行", 6560)]),
  row([cell("MonitorPage", 2800), cell("系统监控与健康检查", 6560)]),
  row([cell("SettingsPage", 2800), cell("系统配置", 6560)]),
  row([cell("AdminUsersPage", 2800), cell("用户管理（创建/编辑/角色分配）", 6560)]),
  row([cell("AdminAuditLogsPage", 2800), cell("审计日志查看", 6560)]),
  row([cell("AutoRepairDashboardPage", 2800), cell("汽修智能助手主控面板", 6560)]),
  row([cell("AutoRepairKnowledgePage", 2800), cell("汽修知识库管理", 6560)]),
  row([cell("AutoRepairAgentPage", 2800), cell("汽修智能体对话", 6560)]),
]);

// PG 存储架构表
const pgSchemaTable = tbl(TBL_W, [2400, 2200, 4760], [
  row([hcell("存储类型", 2400), hcell("实现", 2200), hcell("说明", 4760)]),
  row([cell("矢量存储", 2400), cell("PGVector + HNSW", 2200), cell("文本块向量存储与相似度检索", 4760)]),
  row([cell("图存储", 2400), cell("LightRAG PG Graph", 2200), cell("实体/关系存储，支持图遍历", 4760)]),
  row([cell("KV 存储", 2400), cell("PGKV (JSONB)", 2200), cell("灵活的键值对存储", 4760)]),
  row([cell("文档状态", 2400), cell("PGDocStatus", 2200), cell("文档处理状态追踪", 4760)]),
  row([cell("认证数据", 2400), cell("pg_auth_repo", 2200), cell("用户、角色、权限、审计日志、Token黑名单", 4760)]),
  row([cell("任务状态", 2400), cell("pg_state_repo", 2200), cell("异步处理任务状态持久化", 4760)]),
  row([cell("KB 元数据", 2400), cell("pg_kb_meta_repo", 2200), cell("知识库元信息存储", 4760)]),
  row([cell("Agent 数据", 2400), cell("pg_agent_repo", 2200), cell("智能体配置、对话记录、消息", 4760)]),
  row([cell("图编辑数据", 2400), cell("pg_graph_edit_repo", 2200), cell("知识图谱编辑操作记录", 4760)]),
]);

// API 端点表
const apiTable = tbl(TBL_W, [2200, 1400, 5760], [
  row([hcell("分组", 2200), hcell("方法", 1400), hcell("端点示例", 5760)]),
  row([cell("认证", 2200), cell("POST", 1400), cell("/api/auth/register, /api/auth/login, /api/auth/refresh", 5760)]),
  row([cell("用户管理", 2200), cell("GET/POST/PUT", 1400), cell("/api/auth/users, /api/auth/users/{id}", 5760)]),
  row([cell("角色管理", 2200), cell("GET/PUT", 1400), cell("/api/auth/users/{id}/roles", 5760)]),
  row([cell("知识库", 2200), cell("GET/POST/DELETE", 1400), cell("/api/kb, /api/kb/{name}", 5760)]),
  row([cell("文件上传", 2200), cell("POST", 1400), cell("/api/upload/{kb_name}", 5760)]),
  row([cell("文档管理", 2200), cell("GET/DELETE", 1400), cell("/api/knowledge/{kb_name}/documents", 5760)]),
  row([cell("查询", 2200), cell("POST", 1400), cell("/api/agent/{kb_name}/stream (SSE)", 5760)]),
  row([cell("智能体", 2200), cell("CRUD", 1400), cell("/api/agents, /api/agents/{id}", 5760)]),
  row([cell("对话", 2200), cell("POST/GET", 1400), cell("/api/agents/{id}/conversations", 5760)]),
  row([cell("工作流", 2200), cell("POST/GET", 1400), cell("/api/workflows/{id}/execute", 5760)]),
  row([cell("监控", 2200), cell("GET", 1400), cell("/api/monitor, /api/health, /metrics", 5760)]),
  row([cell("WebSocket", 2200), cell("WS", 1400), cell("/ws/{run_id} (实时进度推送)", 5760)]),
]);

// LLM 集成表
const llmTable = tbl(TBL_W, [2400, 6960], [
  row([hcell("集成方式", 2400), hcell("支持的服务/平台", 6960)]),
  row([cell("云 API", 2400), cell("通义千问 (Qwen)、DeepSeek、Minimax、豆包 (Doubao)", 6960)]),
  row([cell("本地部署", 2400), cell("vLLM、Ollama、LMStudio", 6960)]),
  row([cell("嵌入模型", 2400), cell("OpenAI-compatible Embedding API (支持批量嵌入)", 6960)]),
  row([cell("视觉模型", 2400), cell("Qwen-VL、Doubao Vision (图片理解与检索)", 6960)]),
]);

// 环境变量表
const envTable = tbl(TBL_W, [3600, 5760], [
  row([hcell("环境变量", 3600), hcell("说明", 5760)]),
  row([cell("LLM_BINDING_API_KEY / LLM_BINDING_HOST", 3600), cell("LLM API 连接信息", 5760)]),
  row([cell("LLM_MODEL / VISION_MODEL", 3600), cell("文本和视觉模型名称", 5760)]),
  row([cell("EMBEDDING_MODEL / EMBEDDING_DIM", 3600), cell("嵌入模型与维度", 5760)]),
  row([cell("WORKING_DIR", 3600), cell("工作目录（默认 ./rag_storage）", 5760)]),
  row([cell("CHUNKING_STRATEGY", 3600), cell("分块策略（默认 recursive）", 5760)]),
  row([cell("JWT_SECRET / JWT_REFRESH_SECRET", 3600), cell("JWT 签名密钥", 5760)]),
  row([cell("DATABASE_URL", 3600), cell("PostgreSQL 连接字符串", 5760)]),
  row([cell("CORS_ORIGINS", 3600), cell("允许的跨域源", 5760)]),
  row([cell("MAX_UPLOAD_SIZE_MB", 3600), cell("最大上传大小（MB）", 5760)]),
]);

// 代码质量表
const qualityTable = tbl(TBL_W, [2200, 7160], [
  row([hcell("工具", 2200), hcell("用途", 7160)]),
  row([cell("black", 2200), cell("代码格式化", 7160)]),
  row([cell("isort", 2200), cell("导入排序", 7160)]),
  row([cell("flake8", 2200), cell("代码风格检查", 7160)]),
  row([cell("mypy", 2200), cell("静态类型检查", 7160)]),
  row([cell("pytest + pytest-asyncio", 2200), cell("单元测试与异步测试", 7160)]),
  row([cell("pre-commit", 2200), cell("Git 提交前自动检查", 7160)]),
  row([cell("ruff", 2200), cell("Python 代码检查与自动修复", 7160)]),
]);

// 权限矩阵表
const permTable = tbl(TBL_W, [2600, 2260, 2260, 2240], [
  row([hcell("权限", 2600), hcell("Admin", 2260), hcell("Editor", 2260), hcell("Viewer", 2240)]),
  row([cell("users:read / users:write", 2600), cell("✅", 2260), cell("❌", 2260), cell("❌", 2240)]),
  row([cell("kb:read", 2600), cell("✅", 2260), cell("✅", 2260), cell("✅", 2240)]),
  row([cell("kb:write / kb:delete", 2600), cell("✅", 2260), cell("✅", 2260), cell("❌", 2240)]),
  row([cell("agent:read", 2600), cell("✅", 2260), cell("✅", 2260), cell("✅", 2240)]),
  row([cell("agent:write / agent:delete", 2600), cell("✅", 2260), cell("✅", 2260), cell("❌", 2240)]),
  row([cell("settings:read / settings:write", 2600), cell("✅", 2260), cell("❌", 2260), cell("❌", 2240)]),
  row([cell("audit:read", 2600), cell("✅", 2260), cell("❌", 2260), cell("❌", 2240)]),
  row([cell("monitor:read", 2600), cell("✅", 2260), cell("❌", 2260), cell("❌", 2240)]),
  row([cell("graph:read", 2600), cell("✅", 2260), cell("✅", 2260), cell("✅", 2240)]),
  row([cell("graph:write", 2600), cell("✅", 2260), cell("✅", 2260), cell("❌", 2240)]),
  row([cell("workflow:read / workflow:write", 2600), cell("✅", 2260), cell("✅", 2260), cell("❌", 2240)]),
  row([cell("autorepair:read / autorepair:write", 2600), cell("✅", 2260), cell("✅", 2260), cell("❌", 2240)]),
]);

// ── 构建文档 ─────────────────────────────────────
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: "1B3A5C" },
        paragraph: { spacing: { before: 360, after: 240 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "2B579A" },
        paragraph: { spacing: { before: 280, after: 180 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "3A6DB5" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [
    // ═══════════════════ 封面 ═══════════════════
    {
      properties: {
        page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
      },
      children: [
        new Paragraph({ spacing: { before: 3600 } }),
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
          children: [new TextRun({ text: "RAG-Anything", font: "Arial", size: 72, bold: true, color: "1B3A5C" })] }),
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 },
          children: [new TextRun({ text: "系统架构与技术栈文档", font: "Arial", size: 48, bold: true, color: "2B579A" })] }),
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 600 },
          children: [new TextRun({ text: "System Architecture & Technology Stack", font: "Arial", size: 32, color: "666666", italics: true })] }),
        new Paragraph({ alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 6, color: "1B3A5C", space: 12 } },
          spacing: { before: 400, after: 200 },
          children: [new TextRun({ text: "Version 1.3.1 | 2026-07-03", font: "Arial", size: 24, color: "888888" })] }),
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
          children: [new TextRun({ text: "Author: Zirui Guo", font: "Arial", size: 22, color: "888888" })] }),
        new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Repository: github.com/HKUDS/RAG-Anything", font: "Arial", size: 22, color: "888888" })] }),
      ],
    },

    // ═══════════════════ 目录 + 正文 ═══════════════════
    {
      properties: {
        page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
      },
      headers: {
        default: new Header({ children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "1B3A5C", space: 4 } },
          children: [
            new TextRun({ text: "RAG-Anything", font: "Arial", size: 18, bold: true, color: "1B3A5C" }),
            new TextRun({ text: "  |  System Architecture Document", font: "Arial", size: 18, color: "888888" }),
          ] })] }),
      },
      footers: {
        default: new Footer({ children: [new Paragraph({
          border: { top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 4 } },
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Page ", font: "Arial", size: 18, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: "888888" })] })] }),
      },
      children: [
        // ── 目录 ─────────────────────────────────────
        h1("目录 (Table of Contents)"),
        new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-3" }),
        brk(),

        // ═══════════════════ 第1章 ═══════════════════
        h1("1. 系统概述 (System Overview)"),
        p("RAG-Anything 是一个全流程多模态 RAG (Retrieval-Augmented Generation) 系统，由香港大学 (HKU) 数据科学实验室开发。它将文档解析、多模态内容处理、向量检索、知识图谱与 Agentic RAG 融合为一个统一平台，提供从文档上传到智能问答的完整闭环。"),

        h2("1.1 核心特性 (Core Features)"),
        ...[
          "多模态文档解析：支持 PDF、Word、Excel、PPT、Markdown、图片、视频等多种格式，集成 MinerU、Docling、PaddleOCR、Marker 等多种解析引擎。",
          "混合检索引擎：RRF (Reciprocal Rank Fusion) 融合 BM25 关键词检索、向量语义检索、知识图谱检索三通道。",
          "知识图谱 (GraphRAG)：自动实体/关系提取、图查询、图可视化、图编辑。",
          "Agentic RAG：ReAct/CoT 多步推理引擎，支持工具调用、流式输出。",
          "智能体管理：可配置的 AI 智能体，支持多轮对话、历史记录、答案编辑。",
          "工作流引擎：DAG 编排，6 种节点类型（解析/分块/嵌入/图谱/查询/多模态）。",
          "多知识库管理：支持多个独立知识库实例，每个 KB 独立配置。",
          "RBAC 权限体系：admin/editor/viewer 三级角色，精细到 resource:action 级别的权限控制。",
          "汽修智能助手 (AutoRepair)：专项模块，包含故障案例库、工艺库、知识图谱、部署平台。",
        ].map(bullet),

        h2("1.2 系统定位 (System Positioning)"),
        p("RAG-Anything 定位为一个全流程多模态 RAG 中台，既可以作为 Python 库 (pip install raganything) 嵌入到其他项目中，也可以通过 FastAPI 服务器 + React 前端独立部署。它的核心依赖是 LightRAG 框架，在此基础上增加了多模态处理、混合检索、工作流编排、RBAC 等企业级功能。"),
        brk(),

        // ═══════════════════ 第2章 ═══════════════════
        h1("2. 技术栈概览 (Technology Stack)"),

        h2("2.1 后端 (Backend)"),
        backendTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("2.2 前端 (Frontend)"),
        frontendTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("2.3 数据层 (Data Layer)"),
        dataLayerTable,
        brk(),

        // ═══════════════════ 第3章 ═══════════════════
        h1("3. 系统架构 (System Architecture)"),

        h2("3.1 整体架构概览"),
        p("RAG-Anything 采用前后端分离架构，后端为 FastAPI 服务器，前端为 React SPA。主要组件包括："),
        ...[
          "Web 层：FastAPI 负责 HTTP/WebSocket 请求处理，包括 CORS、安全头、限流、请求大小限制。",
          "路由层 (Routers)：auth、knowledge、agent、admin 四大路由模块，统一注入到 server.py。",
          "服务层 (Services)：提供 KB 实例管理、认证、WebSocket、任务状态、图编辑、Agent 管理等服务。",
          "核心层 (Core)：RAGAnything 主类、查询混入 (QueryMixin)、处理混入 (ProcessorMixin)、批量混入 (BatchMixin)。",
          "引擎层：LightRAG 提供向量存储、图存储、实体提取、文档状态追踪。",
          "数据层：PostgreSQL 作为唯一存储后端，存储矢量、图、元数据、认证信息。",
          "前端层：React SPA，通过 REST API + WebSocket 与后端交互。",
        ].map(bullet),

        h2("3.2 模块组织 (Module Organization)"),
        moduleTable,
        brk(),

        // ═══════════════════ 第4章 ═══════════════════
        h1("4. 后端架构详解 (Backend Architecture)"),

        h2("4.1 FastAPI 服务器"),
        p("server.py 是应用入口，初始化 FastAPI 实例并配置中间件链："),
        ...[
          "SecurityHeadersMiddleware：添加 CSP、HSTS、X-Frame-Options 等安全响应头。",
          "CORSMiddleware：通过 CORS_ORIGINS 环境变量控制跨域访问。",
          "RequestSizeMiddleware：限制上传文件大小（默认 500MB）和请求体大小（默认 10MB）。",
          "Rate Limiting：slowapi 实现基于 IP 的访问频率限制（默认 120/min）。",
          "Prometheus Monitoring：集成 prometheus_fastapi_instrumentator，提供 /metrics 端点。",
          "磁盘监控：异步循环检查存储目录大小，超阈值时告警。",
          "日志轮转：RotatingFileHandler 自动轮转日志文件。",
        ].map(bullet),

        h2("4.2 路由设计 (Router Design)"),
        routerTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("4.3 认证与授权 (Authentication & Authorization)"),
        p("RAG-Anything 实现了完整的基于角色的访问控制 (RBAC) 体系："),
        ...[
          "认证：JWT Token（HS256）+ Refresh Token 机制。Access Token 默认 1 小时过期，Refresh Token 7 天。",
          "安全：bcrypt 密码哈希、账户锁定保护（5次失败锁定 15 分钟）、Token 黑名单、服务器启动唯一标识符。",
          "角色：admin（全部权限）、editor（读写知识库和智能体）、viewer（只读）。",
          "权限模型：Permission 类定义 resource:action 格式的权限常量，包括 users、kb、agent、settings、audit、monitor、workflow、graph、autorepair 等资源。",
          "依赖注入：require_permission() FastAPI 依赖项，在路由层声明式检查。",
          "审计日志：记录所有操作日志（登录、操作、权限变更），支持分页查询。",
          "存储：所有认证数据存储在 PostgreSQL 中，由 pg_auth_repo 服务统一管理。",
        ].map(bullet),
        brk(),

        h2("4.4 文档处理流水线 (Document Processing Pipeline)"),
        p("文档处理是 RAG-Anything 最核心的流程，包含以下步骤："),
        ...[
          "第一步——文件上传 (Upload)：通过 multipart/form-data 上传文件，计算 SHA256 哈希，支持重复文件检测。",
          "第二步——解析 (Parse)：根据文件类型选择解析器（MinerU/Docling/PaddleOCR/Marker），输出 Markdown 格式内容。",
          "第三步——分块 (Chunk)：应用分块策略（recursive/sentence/structure/semantic/agentic），将文档拆分为可检索块。",
          "第四步——嵌入 (Embed)：将文本块转换为向量并存储到 PostgreSQL PGVector。",
          "第五步——图提取 (Graph Extraction)：LightRAG 自动提取实体和关系，构建知识图谱。",
          "第六步——多模态处理 (Multimodal)：单独处理图片、表格、公式、视频等多模态内容。",
        ].map(t => new Paragraph({ numbering: { reference: "numbers", level: 0 }, spacing: { after: 80, line: 340 },
          children: [new TextRun({ text: t, font: "Arial", size: 21 })] })),

        p("解析器支持的文件格式包括："),
        parserTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("4.5 分块策略 (Chunking Strategies)"),
        chunkTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("4.6 查询管线 (Query Pipeline)"),
        p("查询管线是系统的核心智能层，提供多种查询模式："),
        ...[
          "混合查询 (RRF)：BM25 + Vector + Graph 三通道并行检索，通过 Reciprocal Rank Fusion 融合排序。支持可配置的通道权重。",
          "图查询 (Graph)：基于知识图谱的实体匹配 + 多跳邻居遍历，支持局部/全局模式。",
          "多模态查询：同时检索文本和多模态内容（图片、表格、公式）。",
          "VLM 增强查询：使用视觉语言模型处理图片内容，融合文本查询结果。",
        ].map(bullet),

        p("混合检索架构如下："),
        cblock("HybridSearchEngine"),
        cblock("  |-- BM25 Channel: Okapi BM25 + jieba tokenizer"),
        cblock("  |-- Vector Channel: LightRAG HNSW index"),
        cblock("  |-- Graph Channel: GraphRetriever (entity match + BFS)"),
        cblock("  |-- RRF Fusion: Sigma 1/(k + rank_i)  ->  merged results"),
        new Paragraph({ spacing: { after: 200 } }),

        h2("4.7 知识图谱 (Knowledge Graph)"),
        p("知识图谱是系统的重要组件，包含以下功能："),
        ...[
          "实体提取：LightRAG 自动从文档中提取实体和关系，支持自定义实体类型。",
          "图检索：GraphRetriever 提供实体模糊匹配 + BFS 多跳邻居遍历。",
          "图可视化：前端 D3.js 力导向图渲染知识图谱。",
          "图编辑：支持实体/关系的增删改查，实时同步到 PostgreSQL。",
          "存储：图数据存储在 PostgreSQL 中，支持 ACID 事务。",
        ].map(bullet),

        h2("4.8 Agentic RAG"),
        p("AgenticRAG 是系统的高级智能层，实现多步推理能力："),
        ...[
          "ReAct 模式：Thought -> Action -> Observation 循环，最多 5 步。",
          "CoT 模式：链式思维推理，逐步推导答案。",
          "工具注册：支持注册自定义工具（搜索、计算器、API 调用等）。",
          "流式输出：实时流式推送每个推理步骤。",
          "审计追踪：记录完整推理过程供审计分析。",
        ].map(bullet),
        brk(),

        h2("4.9 工作流引擎 (Workflow Engine)"),
        p("WorkflowExecutor 提供 DAG 工作流编排与执行，支持 6 种节点类型："),
        workflowTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("4.10 汽修智能助手 (AutoRepair)"),
        p("AutoRepair 是一个专项子系统，专注于汽车维修领域的智能化应用："),
        ...[
          "agent/：智能体模块（qa_engine、code_parser、lineage_pusher、source_tracer）。",
          "knowledge_graph/：知识图谱模块（parser、tagger、graph_api）。",
          "knowledge_pipeline/：知识管线（fault_case_library、process_library、exam_structurer、scoring_digitizer、textbook_aligner）。",
          "deployment/：部署模块（tiangong_platform、school_deployer、ops_monitor、test_harness）。",
        ].map(bullet),
        brk(),

        // ═══════════════════ 第5章 ═══════════════════
        h1("5. 前端架构 (Frontend Architecture)"),

        h2("5.1 技术选型"),
        p("前端采用 React 18 作为 UI 框架，Vite 5 作为构建工具，Tailwind CSS 3 作为样式解决方案。主要依赖包括："),
        ...[
          "react-router-dom v6：客户端路由，支持路由级代码拆分 (lazy loading)。",
          "framer-motion：页面过渡动画和微交互。",
          "D3.js v7：知识图谱可视化，力导向图渲染。",
          "xyflow (React Flow) v12：工作流编辑器，拖拽式节点配置。",
          "react-markdown + rehype-raw：Markdown 内容渲染。",
          "Recharts：数据图表（统计、分析）。",
          "lucide-react：图标库。",
        ].map(bullet),

        h2("5.2 页面结构 (Page Structure)"),
        pagesTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("5.3 状态管理"),
        p("前端使用 React Context API 实现全局状态管理："),
        ...[
          "AuthContext：提供 user、token、login、logout、refreshToken 等全局认证状态。",
          "ProtectedRoute：路由守卫组件，检查登录状态和角色权限。",
          "API 层：统一的 api.js 模块，自动添加 Authorization 头，处理 Token 过期。",
        ].map(bullet),
        brk(),

        // ═══════════════════ 第6章 ═══════════════════
        h1("6. 数据层设计 (Data Layer Design)"),

        h2("6.1 PostgreSQL 存储架构"),
        p("PostgreSQL 是系统的唯一存储后端（强制，无 SQLite 降级），承载以下数据类型："),
        pgSchemaTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("6.2 上传文件存储"),
        p("上传的原始文件存储在本地文件系统中，结构如下："),
        cblock("working_dir/"),
        cblock("  {kb_name}/"),
        cblock("    uploads/        # 原始上传文件"),
        cblock("    parsing/        # 解析后的 Markdown 内容"),
        cblock("    images/         # 提取的图片文件"),
        cblock("    logs/           # 日志文件"),
        cblock("    metadata.json   # KB 元数据"),
        brk(),

        // ═══════════════════ 第7章 ═══════════════════
        h1("7. API 设计 (API Design)"),

        h2("7.1 RESTful API 概览"),
        p("系统 API 遵循 RESTful 设计原则，主要端点分组如下："),
        apiTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("7.2 LLM 集成"),
        p("系统通过 OpenAI-compatible API 协议集成多种 LLM 服务："),
        llmTable,
        brk(),

        // ═══════════════════ 第8章 ═══════════════════
        h1("8. 部署架构 (Deployment Architecture)"),

        h2("8.1 部署模式"),
        p("RAG-Anything 支持多种部署模式："),

        h3("8.1.1 单机部署"),
        p("最简单的部署方式，适合开发和小规模使用："),
        cblock("# 1. 启动 PostgreSQL (确保 pgvector 扩展安装)"),
        cblock("# 2. 配置 .env 文件 (数据库连接、LLM API Key 等)"),
        cblock("# 3. 启动后端"),
        cblock("python server.py"),
        cblock("# 4. 启动前端"),
        cblock("cd frontend && npm run dev"),

        h3("8.1.2 容器化部署"),
        p("通过 Docker Compose 编排多服务："),
        ...[
          "raganything-server: FastAPI 服务器容器",
          "raganything-frontend: Nginx + React 静态文件",
          "postgres: PostgreSQL + pgvector 扩展",
          "可选：Redis (缓存)、Prometheus + Grafana (监控)",
        ].map(bullet),

        h2("8.2 环境变量配置"),
        p("系统通过 .env 文件和环境变量进行配置，主要配置项包括："),
        envTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("8.3 CI/CD"),
        p("项目使用 GitHub Actions 进行持续集成："),
        ...[
          "test.yaml：运行 pytest 测试套件。",
          "linting.yaml：代码风格检查（black、isort、flake8、mypy）。",
          "pypi-publish.yml：发布 Python 包到 PyPI。",
          "pre-commit：本地提交前检查。",
        ].map(bullet),
        brk(),

        // ═══════════════════ 第9章 ═══════════════════
        h1("9. 安全架构 (Security Architecture)"),

        h2("9.1 安全防护层"),
        p("系统在多个层面实施安全措施："),
        ...[
          "传输层：CSP、HSTS、X-Frame-Options、X-XSS-Protection、Referrer-Policy 等安全响应头。",
          "认证层：JWT Token + Refresh Token 双令牌机制、bcrypt 密码哈希、账户锁定保护、Token 黑名单。",
          "授权层：RBAC 精细权限控制，每个 API 端点声明式检查权限。",
          "输入层：查询输入校验、文件类型校验、请求大小限制、速率限制。",
          "日志层：审计日志记录所有操作、敏感信息脱敏。",
          "数据层：PostgreSQL ACID 事务保证数据一致性。",
        ].map(bullet),

        h2("9.2 权限矩阵 (Permission Matrix)"),
        permTable,
        brk(),

        // ═══════════════════ 第10章 ═══════════════════
        h1("10. 性能与可观测性 (Performance & Observability)"),

        h2("10.1 性能优化"),
        ...[
          "批量嵌入：embedding_batch_size 控制批量大小，减少 API 往返次数。",
          "并发控制：entity_extract_concurrency 控制实体提取并发数。",
          "嵌入缓存：EmbeddingCache 减少重复嵌入调用。",
          "查询缓存：QueryCache 缓存相同查询结果。",
          "异步处理：asyncio + BackgroundTasks 处理耗时任务。",
          "自适应并发：adaptive_concurrency 动态调整并发级别。",
          "BM25 线程池：共享 ThreadPoolExecutor，避免线程泄漏。",
        ].map(bullet),

        h2("10.2 监控与可观测性"),
        ...[
          "Prometheus Metrics：请求数、响应时间、状态码分布、当前请求数。",
          "存储指标：磁盘使用量、文件数量。",
          "健康检查：/api/health 端点。",
          "WebSocket 事件：实时处理进度推送、事件日志。",
          "日志轮转：自动轮转日志文件，支持可配置的大小和备份数。",
        ].map(bullet),
        brk(),

        // ═══════════════════ 第11章 ═══════════════════
        h1("11. 开发规范 (Development Practices)"),

        h2("11.1 代码质量工具"),
        qualityTable,
        new Paragraph({ spacing: { after: 200 } }),

        h2("11.2 项目结构规范"),
        ...[
          "模块化设计：每个 Python 模块头部注释声明 Layer、Primary Responsibility、Key Dependencies。",
          "类型标注：使用 typing 模块（Optional、Callable、Dict、List 等）。",
          "数据类：使用 dataclass 定义配置和数据模型。",
          "API 文档：使用 Pydantic 模型自动生成 OpenAPI 文档。",
          "环境变量：统一通过 get_env_value 读取，支持类型转换。",
        ].map(bullet),
        brk(),

        // ═══════════════════ 第12章 ═══════════════════
        h1("12. 副录 (Appendix)"),

        h2("12.1 关键依赖列表"),
        bp("核心依赖：", "lightrag-hku < 1.5, huggingface_hub, mineru[core], tqdm"),
        bp("数据库：", "asyncpg, psycopg2-binary, pgvector"),
        bp("Web 框架：", "fastapi, uvicorn, slowapi, prometheus-fastapi-instrumentator"),
        bp("认证：", "pyjwt, passlib[bcrypt]"),
        bp("文档处理：", "Pillow, reportlab, weasyprint, markdown, pygments"),
        bp("LLM：", "openai (兼容 API)"),
        bp("前端：", "react 18, vite 5, tailwindcss 3, d3 7, xyflow/react 12, framer-motion 11, lucide-react, react-markdown, rehype-raw, recharts"),

        h2("12.2 版本历史"),
        p("当前版本：1.3.1"),
        p("RAG-Anything 持续迭代，从最初的单一文档解析工具，发展为涵盖解析、检索、图谱、智能体、工作流、汽修专项的全流程 RAG 平台。主要里程碑包括："),
        ...[
          "v1.0: 基础文档解析 + LightRAG 集成",
          "v1.1: 多模态处理、混合检索、工作流引擎",
          "v1.2: RBAC 权限体系、智能体管理、AutoRepair 专项",
          "v1.3: 图编辑、分块详情面板、答案编辑、性能优化",
        ].map(bullet),

        h2("12.3 参考链接"),
        ...[
          "GitHub: https://github.com/HKUDS/RAG-Anything",
          "LightRAG: https://github.com/HKUDS/LightRAG",
          "MinerU: https://github.com/opendatalab/MinerU",
        ].map(bullet),
      ],
    },
  ],
});

// ── 生成文件 ─────────────────────────────────────
const OUTPUT = "RAG-Anything-System-Architecture.docx";
Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(OUTPUT, buffer);
  console.log(`Document generated: ${OUTPUT} (${(buffer.length / 1024).toFixed(1)} KB)`);
}).catch(err => {
  console.error("Failed to generate document:", err);
  process.exit(1);
});
