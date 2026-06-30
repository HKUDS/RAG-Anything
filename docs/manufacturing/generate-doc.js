const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        AlignmentType, WidthType, BorderStyle, ShadingType, HeadingLevel,
        Header, Footer, PageNumber, TableOfContents } = require('docx');
const fs = require('fs');

const PAGE_WIDTH = 12240;
const PAGE_HEIGHT = 15840;
const CONTENT_WIDTH = 9360;

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 24 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 180, after: 180 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 120, after: 120 }, outlineLevel: 2 } },
    ]
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [{ level: 0, format: "bullet", text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: "bullet", text: "○", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 360 } } } }] },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_WIDTH, height: PAGE_HEIGHT },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [
          new Paragraph({
            children: [new TextRun({
              text: "RAG-Anything 智能制造智能体技术方案",
              bold: true, size: 22, font: "Arial"
            })]
          })
        ]
      })
    },
    footers: {
      default: new Footer({
        children: [
          new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [
              new TextRun({ text: "第 ", size: 20, font: "Arial" }),
              new TextRun({ children: [PageNumber.CURRENT], size: 20, font: "Arial" }),
              new TextRun({ text: " 页", size: 20, font: "Arial" })
            ]
          })
        ]
      })
    },
    children: [
      new Paragraph({
        text: "RAG-Anything 智能制造智能体技术方案",
        heading: HeadingLevel.HEADING_1,
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 400 }
      }),
      new Paragraph({
        text: "目录",
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 240, after: 180 }
      }),
      new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }),
      new Paragraph({ text: "", spacing: { after: 240 } }),

      new Paragraph({ text: "一、项目概述", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({
        children: [new TextRun("RAG-Anything 智能制造智能体是 基于 RAG-Anything 引擎构建的 专业领域智能问答与辅助教学系统，主要面向第六届全国智能制造应用技术技能大赛的院校参赛团队。系统集成了知识图谱、多模态检索、AgenticRAG 推理等核心技术，提供赛题结构化、故障诊断、代码解析、视频定位等功能。")],
        spacing: { after: 180 }
      }),
      new Paragraph({
        children: [new TextRun("系统采用前后端分离架构，后端基于 Python FastAPI 构建，前端采用 React 18 + Vite + TailwindCSS 技术栈，支持院校级数据隔离与私有化部署。")],
        spacing: { after: 180 }
      }),
      new Paragraph({ text: "核心价值", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        children: [new TextRun("赋能教学：将专家知识转化为可检索的智能知识库，降低教师重复性答疑工作量")],
        spacing: { before: 60, after: 60 }
      }),
      new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        children: [new TextRun("提升竞赛水平：通过智能赛题分析、故障诊断模拟、技能路径规划，帮助参赛团队针对性训练")],
        spacing: { before: 60, after: 60 }
      }),
      new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        children: [new TextRun("知识沉淀：将分散的教材、赛题、案例转化为结构化知识资产，实现知识的长期积累与复用")],
        spacing: { before: 60, after: 180 }
      }),

      new Paragraph({ text: "二、系统架构", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "采用 C4 模型，分四层：系统层、容器层、组件层、界面层", spacing: { before: 120, after: 120 } }),

      new Paragraph({ text: "系统层", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("RAG-Anything 引擎：核心检索增强问答引擎，支持多模态文档解析、向量检索、RRF 融合")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("智能制造领域模块：领域知识管道、故障诊断引擎、工艺库管理")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("天工讲堂平台：院校部署、监控看板、用户管理")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "容器层", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [4680, 4680], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "知识图谱服务", bold: true })] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "节点边管理、关系查询、普系书可视化", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("多模态知识管道")] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("文档解析、赛题结构化、教材对齐、视频处理")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("智能体服务")] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("文本问答、故障诊断、视频定位、代码解析")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("部署运维")] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("院校部署、监控、看板、用户管理")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "组件层", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ text: "knowledge_graph: models.py, parser.py, tagger.py, graph_api.py", spacing: { before: 60, after: 60 } }),
      new Paragraph({ text: "knowledge_pipeline: process_library, fault_case_library, exam_structurer, textbook_aligner", spacing: { before: 60, after: 60 } }),
      new Paragraph({ text: "agent: qa_engine, fault_diagnosis, video_locator, code_parser", spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "三、后端技术栈", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "核心框架", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [3500, 5860], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "语言", bold: true })] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "Python 3.10+", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("Web 框架")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("FastAPI 0.110+")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("异步支持")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("Asyncio + Uvicorn")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("RAG 引擎")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("LightRAG 框架")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "数据库与存储", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [3500, 5860], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "向量存储", bold: true })] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "ChromaDB / SQLite Vector Store", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("关系数据库")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("SQLite (默认) / PostgreSQL")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("文件存储")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("本地文件系统 / S3 兼容存储")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("文档解析")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("MinerU 文档解析引擎")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "四、前端技术栈", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "技术选型", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [3500, 5860], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "框架", bold: true })] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "React 18.3.1", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("构建工具")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("Vite 5.4.2")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("路由")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("React Router DOM 6.26.0")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("样式")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("TailwindCSS 3.4.10")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("动画")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("framer-motion 11.5.0")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("知识图谱可视化")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("d3.js 7.9.0")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("图表")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("lucide-react 0.441.0")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("图表")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("recharts 2.12.0")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("工作流编辑器")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("@xyflow/react 12.11.0")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "前端架构设计", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("组件化架构：采用 React Hooks + Context 模式，实现状态管理与组件复用")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("路由守卫：基于 ProtectedRoute 组件实现认证与权限控制")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("API 封装：统一的 utils/api.js 封装，支持请求拦截、响应处理、错误统一管理")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("主题系统：TailwindCSS 自定义主题配置，支持温暖色系、珊瑚色、鼠尾草绿等专业配色方案")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "前端页面结构", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [3500, 5860], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "制造仪表盘", bold: true })] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "ManufacturingDashboardPage.jsx - 数据统计、使用分析", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("制造智能体")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("ManufacturingAgentPage.jsx - 智能问答、代码解析、故障诊断")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("制造知识库")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("ManufacturingKnowledgePage.jsx - 图谱可视化、故障案例库、工艺库")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("通用智能体")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("AgentsPage.jsx, AgentChatPage.jsx")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("知识库管理")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("KnowledgePage.jsx, UploadPage.jsx")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("工作流")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("WorkflowPage.jsx - 可视化工作流编辑器")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("用户管理")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("AdminUsersPage.jsx")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("审计日志")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("AdminAuditLogsPage.jsx")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("监控")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("MonitorPage.jsx")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "前端核心组件", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [4680, 4680], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "KnowledgeGraphD3.jsx", bold: true })] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "D3.js 力导向图可视化，支持拖拽、缩放、节点高亮、关系展示", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("GCodeEditor.jsx")] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("G 代码编辑器，支持语法高亮、指令解析、错误检测")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("VideoSegmentPlayer.jsx")] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("视频分段播放器，支持时间戳定位、帧预览")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("WorkflowCanvas.jsx")] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("工作流画布，基于 @xyflow/react，支持节点拖拽、连线")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "五、核心参数", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "引擎配置", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [3500, 5860], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "parse_method", bold: true })] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "auto", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("parser")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("mineru")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("多模态开关")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("image table equation 开启，video 默认关闭")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("max_concurrent_files")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("1")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "问答引擎参数", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [3500, 5860], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "top_k", bold: true })] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "10", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("citation_required")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("True")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("query_mode")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("rrf")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("max_steps")] })] }),
          new TableCell({ borders, width: { size: 5860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("3")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "故障诊断参数", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [4680, 4680], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "max_dialog_rounds", bold: true })] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "5", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("confidence_threshold")] })] }),
          new TableCell({ borders, width: { size: 4680, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("0.6")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "六、实现方法", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "两级问答策略", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ text: "Tier 1 - 直接检索", bold: true, spacing: { before: 120, after: 120 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("RRF 融合检索：Reciprocal Rank Fusion 算法融合向量检索与关键词检索结果")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("上下文大于等于 200 字符，直接调用 LLM 生成答案")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("上下文小于 50 字符，判定为检索不足，进入 Tier 2")], spacing: { before: 60, after: 180 } }),
      new Paragraph({ text: "Tier 2 - AgenticRAG", bold: true, spacing: { before: 120, after: 120 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("ReAct 循环：思考 (Thought) -> 行动 (Action) -> 观察 (Observation) -> 思考")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("最大步数 3：防止无限循环，控制推理深度")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("自主调用 SearchTool：根据思考结果自动决定是否需要补充检索")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "三级图片匹配", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [3000, 6360], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3000, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "Tier 1 - 图号精确匹配", bold: true })] })] }),
          new TableCell({ borders, width: { size: 6360, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "提取文档中的图号，直接映射到图片序列索引", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3000, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "Tier 2 - Caption 关键词", bold: true })] })] }),
          new TableCell({ borders, width: { size: 6360, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "jieba 分词提取查询关键词，与图片 Caption 做交集匹配", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 3000, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "Tier 3 - 路径关键词", bold: true })] })] }),
          new TableCell({ borders, width: { size: 6360, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "基于文件名和目录名进行关键词匹配，作为兜底策略", bold: true })] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "故障诊断流程", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("用户描述故障现象，系统接收自然语言输入")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("案例库向量匹配：使用余弦相似度 (cosine similarity) 检索相似故障案例")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("选择追问模板：加工精度、表面质量、机械振动、电气故障四大类")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("多轮对话缩范围：根据用户回答逐步排除可能性")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("置信度计算：avg_score * 0.7 + concentration * 0.3")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("置信度 >= 0.8 或 轮数 >= 5，输出诊断结论与建议操作")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "知识图谱", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ text: "节点类型", bold: true, spacing: { before: 120, after: 120 } }),
      new Paragraph({ children: [new TextRun("competition_topic (赛题)、skill_point (技能点)、knowledge_point (知识点)、tool (工具)、standard (标准)")], spacing: { after: 120 } }),
      new Paragraph({ text: "关系类型", bold: true, spacing: { before: 120, after: 120 } }),
      new Paragraph({ children: [new TextRun("requires (前置依赖)、advances_to (进阶关系)、related_to (关联关系)、evaluates (评分标准)、applies_in (应用场景)")], spacing: { after: 180 } }),

      new Paragraph({ text: "教材对齐", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("similarity_threshold = 0.65：语义相似度阈值")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("语义相似度计算：使用预训练模型计算知识点与教材章节的相似度")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("支持人工确认映射关系：自动对齐结果可由教师审核确认")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "赛题结构化", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ text: "支持 PDF、DOCX、DOC、TXT 格式，输出结构化 JSON", spacing: { before: 120, after: 120 } }),
      new Paragraph({ children: [new TextRun("questions 字段：id、type、content、options、answer、skills、difficulty")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ children: [new TextRun("knowledge_nodes 字段：id、name、description、type")], spacing: { after: 180 } }),

      new Paragraph({ text: "七、API 接口", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "认证", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ children: [new TextRun({ text: "Authorization: Bearer jwt_token", font: "Courier New" })], spacing: { before: 60, after: 60 } }),
      new Paragraph({ children: [new TextRun({ text: "X-Institution-ID: institution_id", font: "Courier New" })], spacing: { after: 180 } }),

      new Paragraph({ text: "核心接口", heading: HeadingLevel.HEADING_3 }),
      new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: [2500, 5000, 1860], rows: [
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 2500, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "方法", bold: true })] })] }),
          new TableCell({ borders, width: { size: 5000, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "路径", bold: true })] })] }),
          new TableCell({ borders, width: { size: 1860, type: WidthType.DXA }, shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "功能", bold: true })] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 2500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("POST")] })] }),
          new TableCell({ borders, width: { size: 5000, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "/manufacturing/qa/stream", font: "Courier New" })] })] }),
          new TableCell({ borders, width: { size: 1860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("流式问答")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 2500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("POST")] })] }),
          new TableCell({ borders, width: { size: 5000, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "/manufacturing/code/parse", font: "Courier New" })] })] }),
          new TableCell({ borders, width: { size: 1860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("代码解析")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 2500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("POST")] })] }),
          new TableCell({ borders, width: { size: 5000, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "/manufacturing/fault-diagnosis", font: "Courier New" })] })] }),
          new TableCell({ borders, width: { size: 1860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("故障诊断")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 2500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("GET")] })] }),
          new TableCell({ borders, width: { size: 5000, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "/manufacturing/knowledge-graph/nodes", font: "Courier New" })] })] }),
          new TableCell({ borders, width: { size: 1860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("节点查询")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 2500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("GET")] })] }),
          new TableCell({ borders, width: { size: 5000, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "/manufacturing/knowledge-graph/relations", font: "Courier New" })] })] }),
          new TableCell({ borders, width: { size: 1860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("关系查询")] })] })
        ]}),
        new TableRow({ children: [
          new TableCell({ borders, width: { size: 2500, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("GET")] })] }),
          new TableCell({ borders, width: { size: 5000, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: "/manufacturing/video/locate", font: "Courier New" })] })] }),
          new TableCell({ borders, width: { size: 1860, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun("视频定位")] })] })
        ]})
      ]}),
      new Paragraph({ text: "", spacing: { after: 180 } }),

      new Paragraph({ text: "八、系统应用场景", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "教学辅助", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("知识 Q&A：学生可通过自然语言问答，系统基于知识库回复专业知识")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("教材对齐：将赛题与知识点与教材章节自动对齐，方便教师处理")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("图谱可视化：知识图谱可视化展示，帮助学生理解知识关系")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "技能训练", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("赛题分析：智能分析赛题结构，评价难度，推荐相关知识点")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("G 代码解析：解析 CNC 加工代码，指明工艺要求，定位代码问题")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("技能路径规划：根据学生水平，制定个性化训练方案")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "故障诊断", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("模拟诊断：通过人工智能模拟故障诊断流程，提升学生诊断能力")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("案例库：建立故障案例库，包含常见故障、原因分析、修复方法")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("置信度评估：系统自动计算诊断置信度，鉴定诊断结果可靠性")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "竞赛备战", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("赛题数据库：集成过去年度竞赛题目，支持实时搜索和分析")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("诊断模拟：模仿竞赛中的故障诊断环境，进行训练")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("成绩分析：分析训练成绩，制定提升策略")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "就业指导", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("技能培训：根据智能制造业务要求，设计技能培训路径")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("职业规划：结合学生兴趣和能力，指定职业发展方向")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "九、具体业务价值", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "聚焦业务价值", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("提升教学效率：将教师从重复性答疑中解放出来，重点关注课程设计和系列训练")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("提高竞赛成绩：通过智能化训练和诊断模拟，提升院校竞赛水平")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("知识沉淀与复用：将分散的教材、赛题、案例转化为结构化知识资产")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("个性化教育：根据学生个体情况，制定个性化训练方案")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "科学研究价值", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("知识图谱研究：为智能制造领域知识图谱建立和应用提供研究平台")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("RAG 技术研究：研究多模态 RAG、AgenticRAG 等新兴技术在职业教育中的应用")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("人工智能诊断：研究人工智能在智能制造故障诊断中的应用方法")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "行业应用潜力", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("工业机械设备：可用于工业场景下的机器设备故障诊断")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("CNC 加工中心：为 CNC 加工中心提供智能化矫正和代码解析")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("智慧工厂：为智慧工厂的智能化转型提供知识支持")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "十、开发与部署", heading: HeadingLevel.HEADING_2 }),
      new Paragraph({ text: "开发环境", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ children: [new TextRun({ text: "Python 3.10+, Node.js 18+", font: "Courier New" })], spacing: { before: 60, after: 60 } }),
      new Paragraph({ children: [new TextRun({ text: "npm install && pip install -r requirements.txt", font: "Courier New" })], spacing: { after: 180 } }),

      new Paragraph({ text: "部署方式", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("本地部署：Python + Node.js 本地启动")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Docker 部署：支持 Docker Compose 一键部署")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("云平台部署：支持 QingCloud、Aliyun 等云平台部署")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "从业方案", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("院校版：基于院校级数据隔离，支持多院校公用")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("私有化版：全部源码开源，支持私有化部署")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("云 SaaS 版：云端部署，无需自己管理环境")], spacing: { before: 60, after: 180 } }),

      new Paragraph({ text: "基础支持", heading: HeadingLevel.HEADING_3 }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("企业级用户：7*24 小时客服支持")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("院校级用户：专业技术工程师定期拜访")], spacing: { before: 60, after: 60 } }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("云 SaaS 用户：技术远程维护，自动工作台启动")], spacing: { before: 60, after: 180 } })
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync('c:\\Users\\98014\\RAG-Anything\\docs\\manufacturing\\manufacturing-doc.docx', buffer);
  console.log('Document generated successfully!');
}).catch(err => {
  console.error('Error generating document:', err);
});
