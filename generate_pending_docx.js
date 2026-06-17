const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat,
  TableOfContents, HeadingLevel, BorderStyle, WidthType, ShadingType,
  PageNumber, PageBreak
} = require('docx');

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cm = { top: 60, bottom: 60, left: 120, right: 120 };
const CW = 9026;

function hdrCell(text, w) {
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA }, margins: cm,
    shading: { fill: "1F4E79", type: ShadingType.CLEAR },
    children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text, font: "微软雅黑", size: 19, bold: true, color: "FFFFFF" })] })]
  });
}
function cell(text, w, opts = {}) {
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA }, margins: cm,
    shading: opts.shade ? { fill: "F7F8FA", type: ShadingType.CLEAR } : undefined,
    children: [new Paragraph({ spacing: { after: 60, line: 320 }, children: [new TextRun({ text, font: "微软雅黑", size: 19, ...(opts.bold ? { bold: true } : {}), ...(opts.color ? { color: opts.color } : {}) })] })]
  });
}
function multiCell(paragraphs, w, opts = {}) {
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA }, margins: cm,
    shading: opts.shade ? { fill: "F7F8FA", type: ShadingType.CLEAR } : undefined,
    children: paragraphs.map(txt => new Paragraph({
      spacing: { after: 60, line: 320 },
      children: [new TextRun({ text: txt, font: "微软雅黑", size: 19, ...(opts.color ? { color: opts.color } : {}) })]
    }))
  });
}

function featureTable(rows, leftW = 3600) {
  const rightW = CW - leftW;
  return new Table({
    width: { size: CW, type: WidthType.DXA },
    columnWidths: [leftW, rightW],
    rows: [
      new TableRow({ children: [hdrCell("功能描述『, leftW), hdrCell(』技术方案与关键参数", rightW)] }),
      ...rows.map((r, i) => new TableRow({
        children: [
          cell(r[0], leftW, { shade: i % 2 === 0, bold: true }),
          multiCell(r[1], rightW, { shade: i % 2 === 0 }),
        ]
      }))
    ]
  });
}

function heading(text, level) {
  const sizes = { 1: 36, 2: 28, 3: 24, 4: 22 };
  return new Paragraph({
    heading: level === 1 ? HeadingLevel.HEADING_1 : level === 2 ? HeadingLevel.HEADING_2 : level === 3 ? HeadingLevel.HEADING_3 : HeadingLevel.HEADING_4,
    spacing: { before: level === 1 ? 360 : level === 2 ? 280 : 200, after: 160 },
    children: [new TextRun({ text, font: "微软雅黑", bold: true, size: sizes[level] || 20, color: "1A1D23" })]
  });
}

function p(text) {
  return new Paragraph({
    spacing: { after: 120, line: 360 },
    children: [new TextRun({ text, font: "微软雅黑", size: 21 })]
  });
}

// ═════════════════════════════════════════════════════════
const doc = new Document({
  styles: {
    default: { document: { run: { font: "微软雅黑", size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "微软雅黑", color: "1A1D23" },
        paragraph: { spacing: { before: 360, after: 180 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "微软雅黑", color: "1A1D23" },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "微软雅黑", color: "1A1D23" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "F59E0B", space: 4 } },
          children: [new TextRun({ text: "RAG-Anything 待开发功能说明书『, font: 』微软雅黑", size: 16, color: "9499A3" })]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 4 } },
          children: [new TextRun({ text: "第 ", font: "微软雅黑", size: 16, color: "9499A3" }),
            new TextRun({ children: [PageNumber.CURRENT], font: "微软雅黑", size: 16, color: "9499A3" }),
            new TextRun({ text: " 页『, font: 』微软雅黑", size: 16, color: "9499A3" })]
        })]
      })
    },
    children: [
      // ═══ COVER ═══
      new Paragraph({ spacing: { before: 2400 } }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
        children: [new TextRun({ text: "RAG-Anything", font: "微软雅黑", size: 56, bold: true, color: "1F4E79" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 },
        children: [new TextRun({ text: "待开发功能说明书『, font: 』微软雅黑", size: 44, bold: true, color: "F59E0B" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
        children: [new TextRun({ text: "多模态知识库智能问答系统 · 后续版本规划『, font: 』微软雅黑", size: 24, color: "5F6570" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 300 },
        children: [new TextRun({ text: "版本 1.0 · 2026年6月『, font: 』微软雅黑", size: 18, color: "9499A3" })] }),

      // ═══ TOC ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("目  录", 1),
      new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }),

      // ═══ OVERVIEW ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("一、开发总览", 1),
      p("本文档为 RAG-Anything 后续版本的功能开发规格说明，涵盖第 2 周至第 4 周的交付项及远期规划。每项功能均标注可行性评估（✅=可行 / ⚠️=时间偏紧 / 🔴=需降级），并附技术方案、实现步骤和验收标准。"),
      p("当前已完成功能共计 16 项，详见《RAG-Anything 已实现功能说明书》。"),

      featureTable([
        ["第 2 周（进行中）",
         ["交付 3 项：HyDE + Multi-Query 查询改写模块、后端模块化重构（5 Router）、Agentic RAG 多步推理引擎。",
          "时间：2026.6.23 — 6.29。"]],
        ["第 3 周（计划交付）",
         ["交付 6 项：RRF 显式三路融合检索、GraphRAG 知识图谱增强、DAG 工作流引擎（MVP 版）、SSO/OIDC 企业认证、多轮对话上下文管理、密钥管理与依赖安全扫描、核心测试覆盖。",
          "时间：2026.6.30 — 7.06。"]],
        ["第 4 周（计划交付）",
         ["交付 5 项：审计日志系统、Docling/Marker 文档解析升级、前端 Zustand + i18n 重构、性能压测与生产调优、项目管理看板集成。",
          "时间：2026.7.07 — 7.13。"]],
        ["远期规划",
         ["7 项：数据集模块、多数据库接入扩展、知识质量检测、非结构化数据打标应用、更多数据源接入、实时协作、移动端适配。时间待定，按需启动。"]],
      ], 3200),

      // ═══ WEEK 2 ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("二、第 2 周交付项（进行中）", 1),

      heading("2.1  HyDE + Multi-Query 查询改写独立模块", 2),
      p("✅ 可行性：可行——本质是 LLM 文本生成 + 去重融合，基础改写代码已在 SSE 管线中存在。"),
      featureTable([
        ["功能目标",
         ["将当前内联在 SSE 流式管线中的查询改写功能封装为独立的可配置模块，新增 HyDE（假设文档嵌入）和 Multi-Query（多路变体生成）两种增强策略。"]],
        ["HyDE 策略",
         ["对用户问题，先生成 3 个假设答案文本（temperature=0.7，每篇 max_tokens=512），再用这些假设答案的向量去检索。这种方式能有效弥补问题表述和答案表述之间的语义鸿沟。",
          "参数：n=3, temperature=0.7, max_tokens=512。"]],
        ["Multi-Query 策略",
         ["将用户问题改写为 3 个不同表述的变体（temperature=0.8，每个 max_tokens=128），与原始问题一并检索，综合所有结果。提升不同表述方式下的召回覆盖率。",
          "参数：n=3, temperature=0.8, max_tokens=128。"]],
        ["融合方式",
         ["原始查询 + 3 个 HyDE 假设文档 + 3 个 Multi-Query 变体 → 共 7 路并行检索 → 去重 → RRF 融合排序。单路超时 30 秒自动跳过，不影响其他路。"]],
        ["文件规划",
         ["新建 raganything/query_rewriter.py：QueryRewriter 类，含 rewrite_hyde()、rewrite_multiquery()、rewrite() 三个方法。在 server.py 的 /api/query/stream 和 /api/agents/{id}/query/stream 中集成调用。"]],
        ["环境变量",
         ["QUERY_REWRITE_STRATEGIES=hyde,multiquery（控制启用策略）。QUERY_REWRITE_TIMEOUT=30（单策略超时秒数）。"]],
        ["验收标准",
         ["输入『年假政策』→生成 3 个假设文档 + 3 个变体查询；召回率相比单查询提升 ≥ 20%；可通过环境变量关闭/启用各策略；查询改写超时自动降级为原始查询。"]],
      ]),

      heading("2.2  后端模块化重构（5 Router）", 2),
      p("✅ 可行性：可行——纯代码搬运，不改变逻辑，每个 Router 文件控制在 400 行以内。"),
      featureTable([
        ["功能目标",
         ["将当前 server.py（约 2300 行单文件）拆分为 5 个独立 Router 文件，提升代码可维护性和团队协作效率。"]],
        ["Router 拆分方案",
         ["① routers/auth.py（~300 行）：/api/auth/* 全部认证端点；",
          "② routers/knowledge.py（~400 行）：/api/knowledge/* + /api/upload/* 知识管理与上传；",
          "③ routers/agent.py（~350 行）：/api/agents/* 智能体管理与对话；",
          "④ routers/query.py（~300 行）：/api/query/* SSE 流式查询管线；",
          "⑤ routers/admin.py（~300 行）：/api/admin/* + /api/settings + /api/monitor/*。"]],
        ["公共依赖提取",
         ["将 limiter、get_current_user、verify_kb_access 等公共依赖提取到 dependencies.py，各 Router 统一引用。"]],
        ["验收标准",
         ["每个 Router 文件 < 400 行；server.py 精简至 < 300 行；所有现有 API 端点路径不变；pytest 全部通过。"]],
      ]),

      heading("2.3  Agentic RAG 多步推理引擎", 2),
      p("⚠️ 可行性：时间偏紧——完整 ReAct 循环 + 工具调用 + 错误恢复需要 1.5-2 周。第 2 周先交付最小版本（2 步推理 + Search 工具），第 3 周完善。"),
      featureTable([
        ["功能目标",
         ["在现有智能体框架基础上实现 ReAct（Thought→Action→Observation 循环）多步推理模式，使智能体能够自主规划检索路径、调用工具、验证结果。"]],
        ["ReAct 推理循环",
         ["用户提问 → Step 1: Thought（分析需要什么信息）→ Action（执行检索/计算/搜索）→ Observation（观察结果是否充分）→ Step 2: 判断是否需要补充检索 → 循环直到信息充分或达到最大步数 → 综合回答。",
          "参数：max_steps=5（最大推理步数），单步超时 30 秒。"]],
        ["内置工具",
         ["第 2 周：SearchTool（知识库检索）+ CalculatorTool（四则运算+三角函数）。",
          "第 3 周追加：DatabaseQueryTool（SQL 生成+执行）、WebSearchTool（联网搜索）。",
          "工具抽象为 Tool 基类（name + description + parameters JSON Schema + async execute()），支持注册自定义工具。"]],
        ["文件规划",
         ["新建 raganything/agentic_rag.py：AgenticRAG 类 + Tool 基类。在 server.py 查询端点中添加 agent_mode 参数（react/cot），由智能体配置控制。"]],
        ["验收标准",
         ["MVP 版：输入『去年销售额最高的产品是什么，比第二名高多少%』→Agent 分 2 步检索+计算；max_steps=5 时不会无限循环；单工具超时 30 秒后自动跳过并记录。"]],
      ]),

      // ═══ WEEK 3 ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("三、第 3 周交付项", 1),

      heading("3.1  RRF 显式三路融合检索", 2),
      p("✅ 可行性：可行——RRF 公式仅一行代码，BM25 和向量搜索已实现，图谱通道基础已有。"),
      featureTable([
        ["功能目标",
         ["在现有 LightRAG hybrid 模式基础上，实现显式的三路独立检索通道 + RRF 融合排序，替代当前的黑盒混合检索，使各通道权重和参数可独立调优。"]],
        ["三路通道",
         ["① BM25 关键词通道（权重 0.3）：Okapi BM25（k1=1.5, b=0.75），jieba 分词，独立 top_k=50；",
          "② 向量语义通道（权重 0.5）：HNSW 余弦检索（M=16, ef=200），独立 top_k=100；",
          "③ 知识图谱通道（权重 0.2）：实体匹配→1-2 跳邻居遍历→关联 chunk 召回，独立 top_k=30。"]],
        ["RRF 融合算法",
         ["score(chunk) = Σ 1/(k + rank_i)，其中 k=60。三路并行检索 → RRF 加权融合 → 统一排序 → 取 Top-N 进入重排序阶段。"]],
        ["文件规划",
         ["新建 raganything/hybrid_search.py：HybridSearchEngine 类，含三个独立搜索方法和 _rrf_fuse() 融合方法。BM25 索引支持增量更新（新文档入库时自动同步）。"]],
        ["验收标准",
         ["三路独立检索并行执行；RRF 融合后 Hit Rate 相比单通道提升 ≥ 50%（📊 目标值，待实测）；P95 延迟 < 200ms；BM25 索引增量更新正常。"]],
      ]),

      heading("3.2  GraphRAG 知识图谱增强检索", 2),
      p("✅ 可行性：可行——实体抽取已有（LightRAG processor），图谱存储已有（NetworkX），需做的是检索管线深度集成和前端可视化。"),
      featureTable([
        ["功能目标",
         ["将现有知识图谱功能从『独立可视化『升级为『深度集成到检索管线"，实现基于实体关系的图谱增强检索和前端 D3 可视化交互。"]],
        ["实体关系抽取",
         ["文档入库时自动调用 LLM 进行实体抽取和关系识别。实体类型包括人物、组织、地点、概念、产品等。关系类型包括就职于、位于、属于、关联等。抽取结果由 LightRAG 引擎内部置信度机制过滤。"]],
        ["图谱检索集成",
         ["在混合检索的第三通道中，识别用户问题中的实体提及 → 在 NetworkX 知识图谱中匹配实体节点 → 1-2 跳邻居遍历 → 收集关联的文档片段 → 参与 RRF 融合排序。"]],
        ["前端可视化",
         ["前端通过 /api/knowledge/graph 获取图谱数据（节点+边），使用 D3 力导向布局渲染。支持节点点击展开邻居、拖拽、缩放、搜索实体等交互操作。"]],
        ["验收标准",
         ["图谱检索通道独立返回结果并参与 RRF 融合；图谱随新文档入库自动更新；前端 D3 力导向图正常渲染并支持交互。"]],
      ]),

      heading("3.3  DAG 可视化工作流引擎（MVP 版）", 2),
      p("🔴 可行性：需降级——完整版（41 种节点 + cron 周期调度 + 完整执行引擎）实际需要 3 周。第 3 周交付 MVP 版：5-8 种核心节点 + 仅手动执行。完整版移至远期规划。"),
      featureTable([
        ["MVP 功能范围",
         ["节点类型：① 数据源（文件上传、数据库连接）② 清洗（字段筛选、去重）③ AI（PDF 解析、文本分段、向量化）④ 输出（导入知识库）。共 5-8 种核心节点，仅支持手动触发执行，不含 cron 周期调度。"]],
        ["前端实现",
         ["使用 React Flow 库实现 DAG 拖拽画布。左侧算子面板（可拖拽节点到画布），右侧节点配置抽屉（基本参数表单），中间画布支持节点拖拽、贝塞尔连线、删除。连线时自动检测并阻止环路（拓扑排序校验）。",
          "页面路径：/admin/workflows。"]],
        ["后端实现",
         ["新建 workflows 和 workflow_runs 两张 PostgreSQL 表。后端 CRUD API：/api/workflows。执行引擎：workflow_engine.py——按拓扑顺序依次执行节点，每个节点独立超时 300 秒，记录输入/输出行数和耗时。"]],
        ["完整版（远期）",
         ["41 种节点类型（含特征工程、ML 模型、NLP、ASR、OCR、VLM 等全部 AI 算子）；cron 周期调度（APScheduler）；节点配置动态表单（根据节点类型自动生成配置界面）；任务运行视图与历史回溯。"]],
      ]),

      heading("3.4  SSO / OIDC 企业统一认证", 2),
      p("✅ 可行性：可行——authlib 库成熟，OIDC 为标准协议，现有 JWT 认证体系完全兼容。"),
      featureTable([
        ["功能目标",
         ["在现有用户名密码登录基础上，增加 OIDC 协议的单点登录支持，兼容 Keycloak、LDAP、OAuth 2.0 等主流企业身份提供商。"]],
        ["技术方案",
         ["使用 authlib 库实现 OIDC Provider 集成。新增两个端点：/api/auth/oidc/login（重定向到 OIDC Provider 授权页）、/api/auth/oidc/callback（处理授权回调，交换 Token，创建/匹配本地用户）。OIDC 用户首次登录时自动创建本地用户记录（username = OIDC sub）。"]],
        ["配置方式",
         ["环境变量控制：OIDC_ENABLED=true（启用开关）、OIDC_ISSUER（身份提供商地址）、OIDC_CLIENT_ID、OIDC_CLIENT_SECRET。关闭时不影响现有用户名密码登录。"]],
        ["验收标准",
         ["可通过 Keycloak 账号登录系统；首次 OIDC 登录自动创建本地用户；现有用户名密码登录不受影响；OIDC Token 过期后自动刷新。"]],
      ]),

      heading("3.5  多轮对话上下文管理", 2),
      p("✅ 可行性：可行——conversations API 已有（/api/agents/{id}/conversations），滑动窗口+摘要压缩是纯逻辑层改动。"),
      featureTable([
        ["功能目标",
         ["为智能体对话增加滑动窗口上下文管理和 LLM 摘要压缩，解决长对话中 Token 消耗线性增长的问题。"]],
        ["滑动窗口策略",
         ["保留最近 10 轮对话（context_window=10，可配置）。超出窗口时触发摘要压缩：前 3 轮保留原文（维持近期语境），3 轮前的对话压缩为 200 字以内的摘要。"]],
        ["摘要压缩",
         ["Token 预算设为 2000（token_budget=2000，可配置）。当上下文总 Token 数超出预算时，调用 LLM 将最早的历史轮次压缩为摘要文本。目标压缩比 ≥ 60%。"]],
        ["前端展示",
         ["对话界面显示『上下文长度指示器"（当前使用 Token 数 / 总预算）。超出预算时提示『历史对话已压缩"。"]],
        ["验收标准",
         ["超过 10 轮对话自动压缩；压缩后 Token 节省 ≥ 60%（📊 目标值）；压缩后的上下文仍能正确回答关联问题。"]],
      ]),

      heading("3.6  密钥管理与依赖安全扫描", 2),
      p("✅ 可行性：可行——两个都是配置+CI 集成类任务，无技术难点。"),
      featureTable([
        ["密钥管理",
         ["当前状态：secrets.token_hex(32) 自动生成密钥（已实现）、.env 管理（已实现）、mask_sensitive_data() 日志脱敏（已实现）。待补充：密钥轮换策略文档（建议每 90 天轮换 JWT_SECRET）、CI 环境变量注入指南（GitHub Secrets / GitLab Variables）。"]],
        ["依赖安全扫描",
         ["CI 集成方案：新建 .github/workflows/security-scan.yml，在每次 PR 时自动运行 pip-audit（Python 依赖）和 npm audit（前端依赖）。高危漏洞（CVSS ≥ 7.0）阻断 PR 合并。定期（每周）全量扫描并自动创建 Issue。"]],
        ["验收标准",
         ["CI 自动运行安全扫描；高危漏洞阻断 PR；密钥无硬编码（CI 检查通过）。"]],
      ]),

      heading("3.7  核心测试覆盖", 2),
      p("✅ 可行性：可行——pytest 已配置，已有 test_auth.py 和 test_core_modules.py 基础测试。"),
      featureTable([
        ["测试范围",
         ["认证模块（100% 覆盖率）：注册/登录/Token刷新/暴力破解锁定/密码复杂度。知识库 CRUD（80%）：创建/删除/文档上传/分段管理。智能问答管线（80%）：REST 查询/SSE 流式/召回测试。智能体管理（80%）：CRUD/模板/对话。分块策略（90%）：6 种策略的输入输出验证。"]],
        ["新增测试文件",
         ["conftest.py（fixtures：test_app, test_client, auth_headers）、test_knowledge_api.py、test_upload.py、test_query_pipeline.py、test_agent_manager.py、test_chunking_strategies.py。"]],
        ["CI 集成",
         [".github/workflows/test.yml：每次 PR 自动运行 pytest --cov=raganything --cov-report=html。覆盖率报告上传至 GitHub Actions Artifacts。"]],
        ["验收标准",
         ["整体覆盖率 ≥ 60%；认证模块覆盖率 100%；CI 自动运行测试；PR 合并前必须通过所有测试。"]],
      ]),

      // ═══ WEEK 4 ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("四、第 4 周交付项", 1),

      heading("4.1  审计日志系统", 2),
      p("✅ 可行性：可行——SQLite 表 + Starlette 中间件，半天工作量。"),
      featureTable([
        ["功能目标",
         ["实现全操作审计追溯：记录每个 API 调用的操作人、IP 地址、操作时间、操作类型、目标资源、操作结果。支持按条件筛选和 CSV 导出。"]],
        ["数据库设计",
         ["新建 SQLite 表 audit_logs（id, user_id, username, ip_address, action, resource_type, resource_id, detail JSON, status, user_agent, created_at）。索引：user_id、action、created_at、resource_type+resource_id。保留期 1 年，定时任务清理过期数据。"]],
        ["中间件实现",
         ["Starlette BaseHTTPMiddleware：在每个 API 请求处理完成后异步写入审计日志，不阻塞响应返回。豁免端点：/api/health（避免日志膨胀）。"]],
        ["查询与导出",
         ["GET /api/audit-logs：支持按 user_id、action、resource_type、start_date、end_date 筛选，分页 page_size=50。GET /api/audit-logs/export：导出为 CSV 文件。"]],
      ]),

      heading("4.2  文档解析管线升级（Docling / Marker 集成）", 2),
      p("⚠️ 可行性：可行但需注意依赖冲突——Docling 和 Marker 各自依赖不同版本的 PyTorch/transformers。建议作为可选依赖，不默认安装。"),
      featureTable([
        ["功能目标",
         ["在现有 MinerU 2.0 解析引擎基础上，增加 Docling（IBM 开源，表格精度高）和 Marker（快速轻量）两种备选解析后端，支持按文档类型自动选择最优引擎。"]],
        ["三引擎对比",
         ["MinerU 2.0（默认）：版面分析+OCR，适用 PDF/扫描件。Docling（新增）：表格识别精度高，适用表格密集型 PDF。Marker（新增）：速度快、内存占用低，适用纯文本批量处理。"]],
        ["自动选择逻辑",
         ["环境变量 PARSER_BACKEND=auto 时：文档包含 > 10 个表格 → Docling；文档 > 50 页纯文本 → Marker；其他 → MinerU。也可手动指定 PARSER_BACKEND=mineru|docling|marker。"]],
        ["安装方式",
         ["作为可选依赖：pip install raganything[docling] 或 pip install raganything[marker] 或 pip install raganything[all]。默认安装仅包含 MinerU，避免强制安装大型依赖。"]],
      ]),

      heading("4.3  前端 Zustand + i18n 国际化重构", 2),
      p("✅ 可行性：可行——Zustand 和 react-i18next 均为成熟 npm 包，纯前端重构。"),
      featureTable([
        ["状态管理迁移",
         ["将当前 React Context（AuthContext）迁移到 Zustand Store。新建 useAuthStore、useKnowledgeStore、useAgentStore、useQueryStore、useUIStore 五个独立 Store。减少不必要的组件重渲染。"]],
        ["国际化（i18n）",
         ["使用 react-i18next + i18next 实现中英文切换。新建 locales/zh-CN/ 和 locales/en-US/ 目录，含 common.json、knowledge.json、agent.json、query.json 四个语言包。所有硬编码中文字符串通过 t() 函数引用语言包。语言偏好存储到 localStorage。"]],
        ["验收标准",
         ["所有页面中英文切换正常；Zustand Store 替代所有 Context；无硬编码中文（全部通过 t() 函数）；语言偏好持久化。"]],
      ]),

      heading("4.4  性能压测与生产调优", 2),
      p("✅ 可行性：可行——locust/k6 均为成熟压测工具。"),
      featureTable([
        ["压测方案",
         ["使用 locust（Python）编写压测脚本。场景：健康检查（200 并发/5min）、登录（50 并发/5min）、文档上传 1MB（20 并发/10min）、知识库查询（50 并发/10min）、流式问答（10 并发/10min）。"]],
        ["调优目标",
         ["QPS ≥ 50（非 AI 接口）、P95 延迟 < 200ms（非 AI 接口）、流式问答首 Token < 5s（依赖于模型 API）。配置调优：Uvicorn workers=CPU 核数、PostgreSQL pool=20、Redis maxmemory=512MB LRU、Nginx worker_connections=1024。"]],
        ["产出",
         ["《性能测试报告》：含各场景 QPS/P50/P95/P99 延迟、资源占用（CPU/内存/磁盘 IO）、瓶颈分析和优化建议。"]],
      ]),

      heading("4.5  项目管理看板集成", 2),
      p("✅ 可行性：可行——独立 HTML 看板已有，移植到 React 组件即可。"),
      featureTable([
        ["功能目标",
         ["将当前的独立 HTML 项目管理看板（项目管理看板.html）集成到主前端应用中，作为 /admin/pm 页面，使用 Zustand Store 管理看板状态，数据从 localStorage 迁移到后端 API。"]],
        ["后端 API",
         ["新建 /api/pm/* 端点：GET /api/pm/tasks（获取全部任务状态）、PUT /api/pm/tasks/{id}（更新任务完成状态）、GET /api/pm/notes/{id}（获取备注）、PUT /api/pm/notes/{id}（更新备注）。"]],
        ["多用户协作",
         ["通过 WebSocket 实现看板状态实时同步：用户 A 标记任务完成 → 推送事件 → 用户 B 的看板自动更新。"]],
      ]),

      // ═══ FUTURE ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("五、远期规划", 1),
      p("以下功能为按需扩展项，启动时间根据实际需求优先级确定。"),

      heading("5.1  数据集模块", 2),
      featureTable([
        ["功能范围",
         ["对标数据中台的数据集管理能力：创建 Clickhouse/Hive 数据集、表结构预览、数据预览（前 1000 条）、SQL 查询（受限 SELECT only）、数据血缘追踪（解析 SQL + 回溯来源）、操作记录。"]],
        ["技术方案",
         ["Clickhouse Python 客户端 + SQLAlchemy Hive 方言。SQL 执行需加白名单限制（仅允许 SELECT，禁止 DDL/DML）。数据血缘通过 sqlparse 解析 SQL AST 实现。"]],
      ]),

      heading("5.2  多数据库接入扩展", 2),
      featureTable([
        ["扩展范围",
         ["在现有 MySQL + PostgreSQL 基础上，增加 Oracle（cx_Oracle）、SQL Server（pyodbc）、TiDB（兼容 MySQL）、MongoDB（motor 异步驱动）、ClickHouse（clickhouse-driver）、Hive（pyhive）的支持。"]],
        ["统一接口",
         ["设计 BaseDBConnector 抽象基类：connect()、list_tables()、get_schema()、query()、close()。各数据库实现对应的 Connector 子类。前端数据源选择器动态加载可用 Connector。"]],
      ]),

      heading("5.3  知识质量检测", 2),
      featureTable([
        ["三项检测",
         ["① 错别字检测：pycorrector 库 + LLM 辅助验证（置信度 ≥ 0.85 标红，一键替换建议词）；② 语句完整性检测：LTP/HanLP 句法分析（检测主语缺失、谓语缺失、句末截断）；③ 敏感词检测：本地敏感词库 + AC 自动机多模式匹配（命中即告警，自动脱敏或提示人工处理）。"]],
      ]),

      heading("5.4  非结构化数据打标应用", 2),
      featureTable([
        ["功能范围",
         ["独立的 AI 打标产品线：预置 ASR 转写、图片理解、主体/产品识别、多维标签打标、情感识别、观点总结、水军内容识别等 AI 应用。支持自定义打标应用（自定义输入字段、提示词、输出字段、数据过滤逻辑）。标签库管理（上传维度表，打标时引用）。错题反馈 + 提示词自动优化（Few-shot 纠错）。"]],
      ]),

      heading("5.5  其他远期项目", 2),
      featureTable([
        ["更多数据源接入",
         ["腾讯云文档、钉钉云文档、金山云文档（私有化）、微信素材库。按甲方实际使用的协作工具决定优先级。"]],
        ["实时协作",
         ["多人实时编辑知识库（WebSocket + CRDT 冲突解决）、评论与标注（数据库 + 实时推送）、任务分配（权限模型扩展）。"]],
        ["移动端适配",
         ["微信小程序（Taro / uni-app 框架）、移动 Web 响应式适配。"]],
      ]),
    ]
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("c:/Users/98014/RAG-Anything/RAG-Anything待开发功能详解.docx", buf);
  console.log("OK: " + buf.length + " bytes");
});
