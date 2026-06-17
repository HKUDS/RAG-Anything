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

function featureTable(rows) {
  return new Table({
    width: { size: CW, type: WidthType.DXA },
    columnWidths: [4000, 5026],
    rows: [
      new TableRow({ children: [hdrCell("功能描述", 4000), hdrCell("实现原理与关键参数", 5026)] }),
      ...rows.map((r, i) => new TableRow({
        children: [
          cell(r[0], 4000, { shade: i % 2 === 0, bold: true }),
          multiCell(r[1], 5026, { shade: i % 2 === 0 }),
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
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "1F4E79", space: 4 } },
          children: [new TextRun({ text: "RAG-Anything 功能实现详解", font: "微软雅黑", size: 16, color: "9499A3" })]
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
            new TextRun({ text: " 页", font: "微软雅黑", size: 16, color: "9499A3" })]
        })]
      })
    },
    children: [
      // ═══ COVER ═══
      new Paragraph({ spacing: { before: 2400 } }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
        children: [new TextRun({ text: "RAG-Anything", font: "微软雅黑", size: 56, bold: true, color: "1F4E79" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 },
        children: [new TextRun({ text: "功能实现详解", font: "微软雅黑", size: 44, bold: true, color: "1A1D23" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
        children: [new TextRun({ text: "多模态知识库智能问答系统", font: "微软雅黑", size: 24, color: "5F6570" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 300 },
        children: [new TextRun({ text: "版本 1.0 · 2026年6月", font: "微软雅黑", size: 18, color: "9499A3" })] }),

      // ═══ TOC ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("目  录", 1),
      new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }),

      // ═══ CH1 ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("一、系统概述", 1),
      p("RAG-Anything 是一套多模态知识库智能问答系统，支持将企业内部的各类文档、表格、图片、音频及视频文件统一接入，经过智能解析与向量化处理后，提供基于自然语言的精准问答服务。系统采用检索增强生成（RAG）架构，在大语言模型基础上引入外部知识库检索能力，确保回答内容可溯源、可验证。"),
      p("系统由四个核心子系统构成：文档解析引擎（多格式文件转化为结构化文本）、知识处理管线（文本分块、向量化和知识图谱构建）、智能检索与问答引擎（多路检索融合和流式回答生成）、安全管理与平台服务（用户认证、权限控制和运维监控）。"),

      // ═══ CH2 ═══
      heading("二、文档解析引擎", 1),

      heading("2.1  文档类文件解析", 2),
      featureTable([
        ["PDF 文档解析",
         ["采用 MinerU 2.0 引擎，处理流程分为五个阶段：",
          "① 版面分析：检测页面中的标题、正文、表格、图片区域及其阅读顺序；",
          "② 文字提取：优先提取原生文字层，扫描件则自动触发 OCR 补充识别；",
          "③ 表格识别：识别合并单元格、跨行跨列的复杂表头结构；",
          "④ 公式提取：自动识别数学公式并转换为 LaTeX 格式；",
          "⑤ 结构化输出：统一以 Markdown 和 JSON 双格式输出。",
          "参数：单文件上限通过 MAX_UPLOAD_SIZE_MB 配置（默认 500 MB），处理超时通过 PROCESS_TIMEOUT 配置（默认 3600 秒 / 60 分钟）。"]],
        ["Office 文档解析",
         ["通过 LibreOffice 无头模式将 doc/docx/ppt/pptx/xls/xlsx 源文件转换为 PDF，随后复用 PDF 解析流程。",
          "Word 文档内嵌的 OMML 数学公式通过自研提取器直接转换为 LaTeX，避免格式丢失。",
          "参数：单文件上限和超时设置与 PDF 相同，由 MAX_UPLOAD_SIZE_MB 和 PROCESS_TIMEOUT 统一控制。"]],
        ["支持的文件格式",
         ["pdf / jpg / jpeg / png / bmp / tiff / gif / webp / doc / docx / ppt / pptx / xls / xlsx / txt / md，共 16 种。",
          "可通过环境变量 PARSE_METHOD 切换解析后端（默认 auto）。"]],
      ]),

      heading("2.2  图像文字识别（OCR）", 2),
      featureTable([
        ["OCR 引擎",
         ["采用 PaddleOCR 开源引擎，部署于服务器本地，无需连接外部网络或调用云端 API。",
          "识别时先通过检测模型定位文字区域，再通过识别模型逐行提取文字，支持中文与英文混合识别。",
          "全程在本地完成，不产生外部 API 调用费用。"]],
      ]),

      heading("2.3  音频与视频处理", 2),
      featureTable([
        ["音频转写",
         ["使用 Whisper 语音识别模型（默认 medium 版本）将音频转为带时间轴的文字。支持中文优先识别和静音段自动过滤（VAD 语音活动检测）。",
          "参数：可通过环境变量切换 Whisper 模型大小（tiny/base/small/medium/large），平衡速度与精度。"]],
        ["视频内容理解",
         ["三步处理流程：",
          "① 关键帧抽取：通过 OpenCV 按固定间隔抽取视频关键帧；",
          "② 视觉理解：调用 VLM 视觉语言模型（默认 Qwen-VL）分析关键帧的画面内容；",
          "③ 音画融合：将 ASR 语音识别结果与 VLM 视觉理解结果按时间轴对齐融合，形成结构化描述。"]],
      ]),

      // ═══ CH3 ═══
      heading("三、知识处理管线", 1),

      heading("3.1  文本分块策略", 2),
      p("大型文档整篇存储时检索精度较低，系统将文档拆分为若干独立片段，每片段作为最小检索单元。默认分块大小为 800 字符，块间重叠 200 字符（可通过 CHUNK_SIZE 和 CHUNK_OVERLAP 环境变量调整）。提供六种分块策略："),
      featureTable([
        ["递归分块（默认）",
         ["按优先级逐级尝试分割：段落分隔符 → 句子分隔符 → 字符级分割。每块默认 800 字符，块间重叠 200 字符。最小块 100 字符，最大块 3000 字符。适用大多数通用文档。"]],
        ["句子级分块",
         ["严格按句号、问号、感叹号等句末标点边界分割，保证每个片段为完整句子。适用于 FAQ、对话记录等语句独立的内容。参数同递归分块。"]],
        ["结构感知分块",
         ["自动识别文档的标题层级（H1-H6）、表格和列表结构，按原文档的章节逻辑边界分割。适用于操作手册、研究报告等结构清晰的文档。"]],
        ["语义相似度分块",
         ["通过 Embedding 模型计算相邻段落的语义相似度，在话题发生转折处分割。适用于语义连贯性重要的长篇文档。每次分块约需 2 次 Embedding 调用。"]],
        ["智能体驱动分块",
         ["由大语言模型自主分析文档结构并判断最佳分割点，效果最优但成本最高（每次分块需调用一次 LLM，约消耗 500 Token）。适用于格式复杂的混合文档。"]],
        ["纯文本分块",
         ["直接按双换行符（空行）分割。适用于已清洗的 Markdown 或纯文本文件，处理速度最快，无额外成本。"]],
      ]),

      heading("3.2  向量化与索引", 2),
      featureTable([
        ["文本向量化",
         ["使用 Embedding 模型将每段文本转换为固定维度的浮点数向量。默认使用 text-embedding-v3（1024 维）。可选替代：BGE-M3（1024 维，开源）、Qwen3-Embedding（4096 维）、Nomic-Embed-Text（768 维）。切换方式：修改环境变量 EMBEDDING_MODEL。",
          "向量维度通过 EMBEDDING_DIM 环境变量指定（默认 1024），距离计算使用余弦相似度。"]],
        ["向量索引",
         ["采用 HNSW（分层可导航小世界图）索引结构，由 LightRAG 引擎内置。该结构在检索精度和速度之间取得了工程平衡。",
          "参数：M=16（每层最大连接数），ef_construction=200（构建时搜索宽度），均为 LightRAG 默认值。"]],
        ["多模态向量化",
         ["支持文本、图片、视频混合输入的统一向量化。图片和视频内容经过视觉理解描述后与文本一并向量化，实现跨模态检索。"]],
      ]),

      heading("3.3  知识图谱构建", 2),
      featureTable([
        ["实体与关系抽取",
         ["系统在文档入库时自动调用大语言模型进行实体抽取和关系识别。实体类型包括人物、组织、地点、概念、产品等；关系类型包括就职于、位于、属于、关联等。抽取结果经过置信度评估后入库。"]],
        ["图谱存储与检索",
         ["实体和关系以 NetworkX 有向图存储，JSON 序列化。检索时采用实体匹配 → 邻居遍历 → 关联片段召回的策略。",
          "图谱数据通过 /api/knowledge/graph 接口对外提供，前端以 D3 力导向布局渲染可视化。"]],
      ]),

      // ═══ CH4 ═══
      heading("四、智能检索与问答引擎", 1),

      heading("4.1  混合检索", 2),
      p("系统默认使用 hybrid 混合检索模式，由 LightRAG 引擎内部融合三种信息来源："),
      featureTable([
        ["关键词检索通道",
         ["采用 Okapi BM25 算法进行关键词匹配，中文分词由 jieba 精确模式处理。BM25 参数使用标准默认值（k1=1.5, b=0.75），综合考虑词频饱和度和文档长度归一化。"],
        ],
        ["向量语义检索通道",
         ["将用户问题通过 Embedding 模型转换为向量，在 HNSW 索引中按余弦距离检索最相近的文档片段。该通道能匹配语义相近但用词不同的内容，是系统最主要的检索通道。",
          "参数：查询时 HNSW ef_search=100（LightRAG 默认），检索数量 top_k 根据智能体配置（默认 40）。"]],
        ["知识图谱检索通道",
         ["识别问题中的实体提及，在知识图谱中遍历邻居节点，收集关联的文档片段。该通道能发现间接相关但问题中未明确提及的内容。",
          "图谱数据由 LightRAG 在文档入库时自动构建，实体和关系存储于 chunk_entity_relation_graph 中。"]],
        ["重排序（Rerank）",
         ["对混合检索返回的候选结果，使用 Cross-encoder 模型进行精细相关性打分。rerank_chunks() 函数负责实现，每个智能体可通过 enable_rerank 选项独立开关。",
          "参数：最终保留 top_n=10 条结果（可配置）。"]],
      ]),

      heading("4.2  流式问答", 2),
      featureTable([
        ["SSE 流式推送",
         ["回答通过 SSE（Server-Sent Events）协议逐 token 推送至前端，避免用户长时间等待。推送流程：系统先发送检索状态（thinking），再逐字输出答案（token），最后发送完成标记（done，含 token 用量统计）。",
          "端点：/api/query/stream（REST SSE）和 /api/agents/{id}/query/stream（WebSocket SSE）两种方式。"]],
        ["答案溯源",
         ["每个回答附带引用标注，格式为 citation:文档名#分段ID，前端可点击直接跳转至原始文档对应段落。检索到的相关图片也一并返回并嵌入回答中。"]],
        ["查询改写（基础版）",
         ["系统在 SSE 流式管线中已集成基础查询改写功能（rewrite_query 函数）。当改写后的查询与原始查询不同时，系统使用改写后的查询进行检索，提升召回覆盖面。",
          "注：HyDE 假设文档嵌入和 Multi-Query 多路变体生成等增强改写策略为后续版本计划，当前尚未独立封装。"]],
      ]),

      heading("4.3  五种检索模式", 2),
      featureTable([
        ["hybrid（混合检索，默认）",
         ["同时使用关键词匹配、向量语义和知识图谱三种通道进行检索并融合结果。适用于大多数通用问答场景。"]],
        ["local（本地检索）",
         ["仅使用关键词和向量通道，不启用知识图谱。适用于对响应速度要求高、实体关联需求不强的场景。"]],
        ["global（全局检索）",
         ["在 local 基础上增强知识图谱的权重，适用于需要跨文档实体关联分析的场景。"]],
        ["naive（朴素检索）",
         ["仅使用基础的向量相似度检索，不经过重排序等后处理步骤。响应速度最快，适用于简单查询。"]],
        ["mix（混合模式）",
         ["综合多种策略的检索模式，由 LightRAG 引擎内部进行策略选择和结果融合。"]],
      ]),

      // ═══ CH5 ═══
      heading("五、知识库管理", 1),

      heading("5.1  知识库类型", 2),
      featureTable([
        ["通用知识库",
         ["存储各类文档、表格、图片、音频和视频。入库时自动完成分块、向量化和知识图谱构建。检索采用混合检索（hybrid 模式）。单知识库上限 5000 文档（可配置）。"]],
        ["QA 问答库",
         ["存储常见问题与标准答案的配对。用户提问时进行向量匹配，相似度达标则直接返回预设答案，确保高频问题的回复一致性和响应速度。单库上限 10000 对。"]],
        ["术语库",
         ["存储专业术语的名称、释义及同义词/近义词列表。用户提问时自动进行术语映射与同义词扩展，提升专业场景下的检索精度。单库上限 5000 术语。"]],
        ["Query 缓存库",
         ["存储高频问题及其已验证的优质答案。用户提问时优先匹配缓存，命中则直接返回，跳过完整检索和推理流程。单库上限 5000 条。"]],
      ]),

      heading("5.2  知识生命周期管理", 2),
      featureTable([
        ["版本控制",
         ["同一文档支持上传多个版本（最多保留 10 个历史版本），系统自动使用最新生效版本进行检索。支持版本间切换与回退。"]],
        ["有效期管理",
         ["每个文档可设置自定义有效期或设为永久有效。到期文档自动标记为 expired，定时任务每日清理，不再参与检索。"]],
        ["启用与禁用",
         ["支持对单个文档或 QA 对实时启用/禁用，禁用后立即停止参与检索，无需重建索引。"]],
        ["标签管理",
         ["支持自定义标签名（≤ 50 字符）和标签值（≤ 200 字符），单文档最多 20 个标签。标签可用于知识分类、检索过滤和动态权限规则。"]],
        ["数据删除",
         ["删除操作同步清除三处数据：PostgreSQL 数据库记录、HNSW 向量索引、原始上传文件。通过事务机制保证一致性。"]],
      ]),

      // ═══ CH6 ═══
      heading("六、安全体系", 1),

      heading("6.1  身份认证", 2),
      featureTable([
        ["密码策略",
         ["最小长度 8 位，必须包含大写字母、小写字母、数字、特殊字符四类中至少三类。密码使用 bcrypt 算法存储（工作因子 12，即 4096 轮哈希计算），即使数据库泄露也无法还原明文。"]],
        ["双 Token 机制",
         ["登录成功后同时发放 Access Token（有效期 24 小时，可配置 JWT_EXPIRY_HOURS）和 Refresh Token（有效期 7 天，使用独立密钥 JWT_REFRESH_SECRET 签名）。Access Token 过期后可凭 Refresh Token 无感续期。"]],
        ["暴力破解防护",
         ["账号级别锁定：同一账号 5 次登录失败后锁定 15 分钟（MAX_FAILED_LOGIN_ATTEMPTS=5, LOGIN_LOCKOUT_MINUTES=15）。锁定状态到期自动解除，登录成功后自动清除失败计数。"]],
        ["JWT 签名",
         ["采用 HMAC-SHA256 算法（HS256），签名密钥为 256 位随机字符串（secrets.token_hex(32)），首次启动时自动生成，确保每个部署实例拥有唯一密钥。"]],
      ]),

      heading("6.2  网络安全", 2),
      featureTable([
        ["API 限流",
         ["基于 slowapi 实现：全局速率 120 次/分钟（可通过 default_limits 配置），登录接口额外独立限流 10 次/分钟，注册接口 5 次/分钟。使用令牌桶算法实现，超频返回 HTTP 429 状态码。"]],
        ["CORS 管理",
         ["通过环境变量 CORS_ORIGINS 配置允许的域名白名单（逗号分隔），禁止 * 通配符。支持指定允许的 HTTP 方法和请求头（Authorization、Content-Type）。"]],
        ["HTTPS 传输",
         ["Nginx 反向代理层强制启用 TLS 1.2 及以上版本，禁止 TLS 1.0/1.1。同时配置安全响应头：X-Content-Type-Options、X-Frame-Options、Content-Security-Policy。"]],
        ["注入防护",
         ["SQL 注入：100% 使用 SQLAlchemy ORM 参数化查询，禁止字符串拼接 SQL。XSS 跨站脚本：前端 React 默认输出转义，后端 bleach 输入清洗。"]],
        ["请求体大小限制",
         ["全局请求体限制 10 MB（MAX_BODY_SIZE_MB），文件上传独立限制 500 MB（MAX_UPLOAD_SIZE_MB），均为可通过环境变量调整的硬限制。"]],
      ]),

      heading("6.3  数据安全", 2),
      featureTable([
        ["密钥管理",
         [".env 环境变量统一管理所有密钥与配置，代码中零硬编码。.env 文件加入 .gitignore 和 .dockerignore，禁止提交至版本控制。"]],
        ["文件上传校验",
         ["上传文件通过扩展名白名单过滤（16 种支持格式），文件大小受 MAX_UPLOAD_SIZE_MB 硬限制。"]],
        ["日志脱敏",
         ["mask_sensitive_data() 函数自动识别日志中的 password、token、secret、key、api_key 等敏感字段并替换为 ***，防止敏感信息通过日志泄露。"]],
        ["权限隔离",
         ["每个知识库操作前强制调用 verify_kb_access(user_id, kb_id) 校验权限。采用 RBAC 两级模型（管理员/普通用户），API 层面和数据库层面双重保证用户只能访问被授权资源。"]],
        ["依赖安全",
         ["定期通过 pip-audit 和 npm audit 扫描项目依赖中的已知漏洞，高危漏洞及时升级修复。"]],
      ]),

      // ═══ CH7 ═══
      heading("七、部署方案", 1),
      featureTable([
        ["容器化架构",
         ["采用 Docker Compose 四服务编排：",
          "① app（FastAPI + Python 3.11 + Uvicorn）：处理所有 API 请求和业务逻辑；",
          "② postgres（PostgreSQL 16 Alpine）：存储知识库元数据、文档信息、用户数据，连接池 20+10 溢出；",
          "③ redis（Redis 7 Alpine）：缓存热点查询结果、存储用户会话和限流计数，最大内存 512 MB，LRU 淘汰策略；",
          "④ nginx（Nginx Alpine）：前端静态资源托管 + HTTPS 反向代理 + TLS 终结。",
          "一键启动命令：docker-compose up -d。所有服务均配置 restart: unless-stopped。"],
        ],
        ["健康检查",
         ["四级检查机制：应用（HTTP GET /api/health，间隔 30 秒，超时 10 秒，启动缓冲 60 秒，失败重试 3 次）、数据库（pg_isready，间隔 10 秒，超时 5 秒，失败重试 5 次）、Redis（TCP 连接检查）、Nginx（内置 HTTP 检查）。"]],
        ["数据持久化",
         ["六个挂载点确保数据不随容器销毁而丢失：rag_storage（知识库向量索引）、uploads（用户上传的原始文件）、output（文档解析中间产物）、auth.db（用户认证信息与审计日志）、pgdata（PostgreSQL 业务数据）、redisdata（Redis 缓存与限流计数数据）。"]],
        ["环境变量配置",
         ["所有运行参数通过 .env 文件统一管理。关键变量包括：LLM_MODEL（推理模型名称）、EMBEDDING_MODEL（向量化模型名称）、JWT_SECRET 和 JWT_REFRESH_SECRET（签名密钥，首次启动自动生成）、CORS_ORIGINS（允许的前端域名）、MAX_UPLOAD_SIZE_MB（文件上传限制，默认 500）、CHUNKING_STRATEGY（默认分块策略，默认 recursive）、PROCESS_TIMEOUT（文档处理超时，默认 3600 秒）。"]],
      ]),

      // ═══ CH8 ═══
      heading("八、模型接入架构", 1),
      p("系统核心设计原则为模型无关性——不绑定特定 AI 厂商。所有模型通过统一接口层抽象，切换模型仅需修改环境变量。"),
      featureTable([
        ["LLM 推理模型",
         ["默认：qwen-max。所有支持 OpenAI /v1/chat/completions 协议的大模型服务均可接入（通义千问全系列、DeepSeek-V3/R1、MiniMax-M3、Ollama 本地模型、LMStudio 等）。",
          "参数：MAX_TOKENS 默认 4096（单次回答最大输出长度），可通过环境变量调整。超时设置：连接超时由 httpx.AsyncClient 管理。"]],
        ["Embedding 向量化模型",
         ["默认：text-embedding-v3（1024 维）。可选：BGE-M3（1024 维，开源）、Qwen3-Embedding（4096 维）、Nomic-Embed-Text（768 维）。",
          "向量维度通过 EMBEDDING_DIM 环境变量配置（默认 1024）。"]],
        ["VLM 视觉理解模型",
         ["默认：qwen-vl-plus（可通过环境变量配置）。用于视频关键帧理解和图片内容分析。支持任意 OpenAI 兼容视觉模型替换。"],
        ],
        ["ASR 语音识别模型",
         ["默认：Whisper medium。用于音频文件转写，支持通过环境变量切换模型大小或替换为 Qwen-Omni。"]],
        ["OCR 文字识别",
         ["PaddleOCR 开源引擎，本地部署运行，即开即用，无 API 调用费用，无需外部网络连接。"]],
        ["Rerank 重排序模型",
         ["默认：Cross-encoder。可选：BGE-Reranker-v2-m3。每个智能体可通过 enable_rerank 选项独立开关。"],
        ],
      ]),

      // ═══ CH9 ═══
      heading("九、智能体管理体系", 1),
      featureTable([
        ["智能体定义",
         ["每个智能体 = 知识库绑定 + LLM 模型配置 + Embedding 模型配置 + 分块策略 + 检索模式 + enable_rerank 开关 + 对话历史。各智能体独立配置，互不干扰。生命周期支持创建、配置、启用、禁用、删除全流程管理。"]],
        ["预置模板（5 种）",
         ["① 通用文档问答（hybrid 模式，top_k=40，默认模板）；",
          "② 学术论文助手（hybrid 模式，top_k=60，严格引用原文）；",
          "③ 代码文档助手（hybrid 模式，top_k=40，突出代码示例）；",
          "④ 精确检索器（local 模式，top_k=20，只返回最相关信息）；",
          "⑤ 创意头脑风暴（global 模式，top_k=80，鼓励发散思维）。",
          "每个模板预设了 temperature、system_prompt、welcome_message 等全套配置，用户可直接使用或在此基础上修改。"]],
        ["对话管理",
         ["每个智能体支持独立的对话线程（ConversationThread）。用户可创建、切换、重命名、删除对话。对话历史持久化存储，支持跨会话恢复。"]],
      ]),

      // ═══ APPENDIX ═══
      new Paragraph({ children: [new PageBreak()] }),
      heading("附录：术语对照", 1),
      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [1800, 2800, 4426],
        rows: [
          new TableRow({ children: [hdrCell("缩写", 1800), hdrCell("全称", 2800), hdrCell("说明", 4426)] }),
          ...[
            ["RAG", "Retrieval-Augmented Generation", "检索增强生成——先检索知识库，再基于检索结果由大模型生成答案"],
            ["Embedding", "文本向量化", "将文字转换为固定维度数字向量，语义相近的文本向量距离更近"],
            ["HNSW", "Hierarchical Navigable Small World", "分层可导航小世界图——一种高效的向量近似最近邻检索算法"],
            ["BM25", "Best Match 25", "基于概率检索模型的关键词匹配算法，对 TF-IDF 的改进"],
            ["RRF", "Reciprocal Rank Fusion", "倒数排名融合——将多路检索结果按排名倒数加权合并的算法（后续版本计划）"],
            ["HyDE", "Hypothetical Document Embeddings", "假设文档嵌入——先生成假设答案再以其向量检索的技术（后续版本计划）"],
            ["SSE", "Server-Sent Events", "服务器推送事件——服务器向浏览器单向推送实时数据的协议"],
            ["OCR", "Optical Character Recognition", "光学字符识别——从图片中自动识别和提取文字"],
            ["ASR", "Automatic Speech Recognition", "自动语音识别——将音频转为文字"],
            ["VLM", "Vision Language Model", "视觉语言模型——能同时处理图像和文本的多模态 AI 模型"],
            ["RBAC", "Role-Based Access Control", "基于角色的访问控制——根据用户角色（管理员/普通用户）分配权限"],
            ["JWT", "JSON Web Token", "一种紧凑的、URL 安全的身份凭证传输格式"],
            ["HSTS", "HTTP Strict Transport Security", "强制浏览器仅通过 HTTPS 访问的安全策略"],
          ].map((r, i) => new TableRow({
            children: [
              cell(r[0], 1800, { shade: i % 2 === 0, bold: true }),
              cell(r[1], 2800, { shade: i % 2 === 0 }),
              cell(r[2], 4426, { shade: i % 2 === 0 }),
            ]
          }))
        ]
      }),
    ]
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("c:/Users/98014/RAG-Anything/RAG-Anything功能实现详解(非技术版).docx", buf);
  console.log("OK: " + buf.length + " bytes");
});
