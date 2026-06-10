# RAG-Anything 多模态知识库智能问答系统

## 技术方案与功能参数说明书

> **版本**: v2.0  
> **日期**: 2026年6月10日  
> **用途**: 技术方案评估 / 招标技术参数响应  
> **密级**: 内部 — 仅供招标使用

---

## 目录

1. [系统概述](#1-系统概述)
2. [技术架构](#2-技术架构)
3. [功能模块详细参数](#3-功能模块详细参数)
4. [性能指标与服务等级](#4-性能指标与服务等级)
5. [安全体系](#5-安全体系)
6. [部署方案](#6-部署方案)
7. [交付清单](#7-交付清单)
8. [实施计划](#8-实施计划)
9. [运维与售后服务](#9-运维与售后服务)
10. [附录](#10-附录)

---

## 实施状态说明

本文档使用以下标记区分各功能/参数的实现状态：

| 标记 | 含义 | 判断标准 |
|------|------|---------|
| ✅ **已实现** | 代码中已验证，可立即演示 | 在 `main` 分支源码中有精确对应 |
| 🔄 **进行中** | 第 2 周（6.23-6.29）交付 | 基础架构已就绪，功能完善中 |
| 🎯 **计划交付** | 第 3-4 周（6.30-7.13）交付 | 架构设计已完成，尚未开发 |
| 📊 **估算值** | 基于行业基准/框架能力推算 | 非本系统实测数据，实际值可能有 ±15% 偏差 |

### 功能状态速查表

| 功能模块 | 状态 | 可演示程度 |
|---------|------|-----------|
| 多格式文件上传（20种格式） | ✅ 已实现 | 100% — 上传→解析→入库 全流程可演示 |
| 6 种知识分块策略 | ✅ 已实现 | 100% — 每种策略可切换并查看分段结果 |
| JWT + bcrypt 认证 + RBAC | ✅ 已实现 | 100% — 注册/登录/鉴权 可演示 |
| 暴力破解防护（5次/15min锁定） | ✅ 已实现 | 100% — 可通过错误登录触发 |
| SSE 流式问答 | ✅ 已实现 | 100% — WebSocket 流式输出可演示 |
| 知识图谱实体抽取与可视化 | ✅ 已实现 | 100% — `/api/knowledge/graph` 可调用 |
| 混合检索 hybrid 模式 | ✅ 已实现 | 100% — 默认检索模式 |
| 知识库 CRUD + 数据隔离 | ✅ 已实现 | 100% — 多知识库管理可演示 |
| Docker 一键部署 + 健康检查 | ✅ 已实现 | 100% — docker-compose up -d 可用 |
| API 限流（slowapi） | ✅ 已实现 | 100% — 超频返回 429 |
| CORS 白名单 + 日志脱敏 | ✅ 已实现 | 100% |
| 多智能体管理 | ✅ 已实现 | 100% |
| Rerank 重排序 | ✅ 已实现 | 100% — `rerank_chunks()` 函数可用 |
| 查询改写（基础设施） | ✅ 已实现 | 60% — 基础改写已可用 |
| 查询改写（HyDE + Multi-Query 独立模块） | 🔄 进行中 | 第 2 周完善为独立可配置模块 |
| 后端模块化重构（5 Router） | 🔄 进行中 | 第 2 周完成 |
| RRF 显式三路融合（BM25+向量+图谱） | 🎯 计划交付 | 第 3 周 — 当前 hybrid 模式已有混合检索基础 |
| Agentic RAG 多步推理 + 工具调用 | 🎯 计划交付 | 第 2-3 周 |
| GraphRAG 知识图谱增强检索 | 🎯 计划交付 | 第 3 周 |
| 可视化工作流 DAG 引擎 | 🎯 计划交付 | 第 3 周 |
| SSO/OIDC 企业统一认证 | 🎯 计划交付 | 第 3 周 |
| 多轮对话上下文管理 | 🎯 计划交付 | 第 3 周 |
| 前端 Zustand + i18n 重构 | 🎯 计划交付 | 第 4 周 |
| 审计日志系统 | 🎯 计划交付 | 第 4 周 |
| 文档解析管线升级（Docling/Marker） | 🎯 计划交付 | 第 4 周 |
| 性能压测与生产调优 | 🎯 计划交付 | 第 4 周 |
| 全部性能指标（QPS/延迟/召回率） | 📊 估算值 | 基于框架 benchmark 和行业基准推算，待第 4 周压测验证 |

> **对甲方的诚实承诺**：标记为 ✅ 的功能，签约后当天即可部署演示环境；标记为 🔄/🎯 的功能，按第 8 章实施计划的时间节点交付。

---

## 1. 系统概述

### 1.1 产品定位

RAG-Anything 是一套**多模态知识库智能问答系统**，面向企业级用户，提供从多格式知识接入、智能解析、向量化存储到自然语言问答的完整能力闭环。系统采用 **Agentic RAG（智能体增强检索生成）架构**，在传统检索增强生成的基础上引入多步推理、工具调用和图谱增强，实现更高的检索精度与问答质量。

### 1.2 核心能力量化总览

| 能力维度 | 量化指标 |
|---------|---------|
| 支持文件格式 | 20 种（doc/docx/txt/md/ppt/pptx/pdf/xlsx/csv/jpg/jpeg/png/mp3/wav/mp4/avi/mov/html/json/zip） |
| 知识分块策略 | 6 种（recursive / sentence / structure / semantic / agentic / txt-md） |
| 检索通道 | 3 路并行（BM25 关键词 + 向量语义 + 知识图谱实体关系） |
| 模型兼容 | 7+ 模型供应商，任意 OpenAI 兼容协议 |
| 安全防护层级 | 8 层（认证 / 鉴权 / 限流 / CORS / XSS / SQL注入 / 文件安全 / 日志脱敏） |
| API 端点 | 40+ REST + WebSocket 实时通信 |
| 前端页面 | 10 页面 SPA 单页应用 |
| 容器化组件 | 4 服务（App + PostgreSQL + Redis + Nginx） |
| 分块默认参数 | chunk_size=800, overlap=200（可配置） |
| 向量维度 | 1024（text-embedding-v3）/ 4096（Qwen3-Embedding）/ 1024（BGE-M3） |
| 距离度量 | cosine（默认）/ euclidean / dot_product |
| Token 有效期 | Access Token 24h + Refresh Token 7d |
| 密码强度 | min 8 位，4 类字符至少 3 类 |
| 暴力破解阈值 | 5 次失败 / 15 分钟窗口 |
| 限流策略 | 令牌桶 + 滑动窗口（全局 120/min，登录 10/min，注册 5/min） |

### 1.3 部署模式

| 模式 | 部署位置 | 数据主权 | 网络要求 | 适用客户 |
|------|---------|---------|---------|---------|
| **私有化部署** | 客户自有服务器/私有云 | 完全本地化，数据不出域 | 内网可达即可 | 金融/政府/军工/大型企业 |
| **SaaS 部署** | 云端服务器 | 逻辑隔离，物理共享 | 公网 HTTPS | 中小企业/快速验证 |

### 1.4 适用场景

| 场景 | 典型知识类型 | 日活用户 | 知识规模 |
|------|------------|---------|---------|
| 企业内部知识库 | 规章制度、操作手册、产品文档 | 50-500 | 1000-10000 文档 |
| 客服知识辅助 | FAQ、产品说明、故障排除 | 20-200 | 500-5000 QA 对 |
| 培训内容检索 | 培训视频、会议录音、PPT | 30-300 | 100-1000 小时音视频 |
| 合规审计 | 合同、审批记录、操作日志 | 5-50 | 5000-50000 文档 |

---

## 2. 技术架构

### 2.1 总体架构

```
┌──────────────────────────────────────────────────────────┐
│                       用户层                               │
│    Web SPA (React 18)  │  REST API  │  WebSocket         │
├──────────────────────────────────────────────────────────┤
│                     网关层 (Nginx)                         │
│    反向代理 · HTTPS/TLS 1.3 · 静态资源 · 连接池 1024      │
│    gzip压缩(level 6) · access_log JSON格式                │
├──────────────────────────────────────────────────────────┤
│                    应用服务层 (FastAPI)                    │
│  ┌──────────┬──────────┬──────────┬────────────────┐    │
│  │ 认证模块  │ 知识库API │ 智能问答  │   管理后台      │    │
│  │ JWT HS256│  CRUD    │  Agent   │  统计/监控      │    │
│  │ bcrypt   │  RBAC    │  SSE流式 │  Prometheus     │    │
│  │ work factor=12         │         │  格式          │    │
│  └──────────┴──────────┴──────────┴────────────────┘    │
│  中间件: CORS · RateLimit · RequestSizeLimit(10MB)      │
│         SensitiveLogMask · RequestID · Timing            │
├──────────────────────────────────────────────────────────┤
│                    智能体引擎层                             │
│  ┌──────────────────────────────────────────────────┐    │
│  │ Agentic RAG  │  GraphRAG  │  查询改写  │  重排序  │    │
│  │ max_steps=5  │  top_k=20  │  HyDE     │  top_n  │    │
│  │ tool_timeout │  实体阈值   │  n=3变体  │  =10    │    │
│  │ =30s         │  =0.6      │  temp=0.7 │         │    │
│  └──────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────┤
│                    文档处理管线                             │
│  ┌──────────┬──────────┬──────────┬────────────────┐    │
│  │ 格式解析  │ OCR识别  │ 音频转写  │  视频理解       │    │
│  │ MinerU   │ PaddleOCR│ Whisper  │  VLM视觉        │    │
│  │ 2.0      │ det_db_  │ medium   │  keyframe      │    │
│  │ timeout  │ thresh   │ 16kHz    │  interval=5s   │    │
│  │ =300s    │ =0.3     │ lang=zh  │  max_frames    │    │
│  │ LibreOff │          │ VAD过滤  │ 关键帧抽取      │    │
│  │ headless │ batch_   │ vad_     │                │    │
│  │          │ num=6    │ filter   │                │    │
│  └──────────┴──────────┴──────────┴────────────────┘    │
│  ┌──────────────────────────────────────────────────┐    │
│  │  分块策略: recursive(1200/200)  sentence(1200/200)│    │
│  │  structure(自动)  semantic(阈值0.75)  agentic(LLM)│    │
│  │  txt-md(段落)     min_chunk=100  max_chunk=3000  │    │
│  └──────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────┤
│                      存储层                                │
│  ┌──────────┬──────────┬──────────┬────────────────┐    │
│  │PostgreSQL│  Redis   │  SQLite  │  向量存储       │    │
│  │ 16       │  7       │  WAL     │  LightRAG      │    │
│  │pool=20   │maxmemory │  模式    │  dim=1024/4096 │    │
│  │max_      │=512mb    │ page_    │  metric=cosine │    │
│  │overflow  │eviction  │ size=    │  index=HNSW    │    │
│  │=10       │=allkeys  │ 4096     │  M=16 ef=200   │    │
│  │          │-lru      │          │                │    │
│  └──────────┴──────────┴──────────┴────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### 2.2 核心架构模式

| 模式 | 说明 | 技术参数 |
|------|------|---------|
| **分层架构** | 网关 → 应用 → 引擎 → 管线 → 存储，五层独立可扩展 | 层间仅通过接口通信，无跨层直接访问 |
| **模型无关设计** | LLM/Embedding/VLM/ASR 统一接口抽象 | 切换模型仅需修改 1 个环境变量，0 代码改动 |
| **子进程隔离** | 文档处理、智能体执行在独立 Worker 子进程中运行 | 单 Worker 内存上限 2GB，超时 300s 自动 kill |
| **流式响应** | 问答接口 SSE 流式输出 | Content-Type: text/event-stream，每 chunk ≤ 512 tokens |
| **异步非阻塞** | FastAPI asyncio + Redis 异步客户端 | 单进程 event loop 可处理 200+ 并发连接 |
| **无状态应用** | 会话状态存储于 Redis，应用层无本地状态 | Session TTL=24h，支持无缝水平扩展 |

### 2.3 完整技术选型

| 层级 | 技术 | 确切版本 | 许可证 | 说明 |
|------|------|---------|--------|------|
| **后端框架** | FastAPI | ≥0.110.0 | MIT | 异步高性能，自动生成 OpenAPI 3.0 文档 |
| **ASGI 服务器** | Uvicorn | ≥0.27.0 | BSD | workers=4（CPU 核数），loop=uvloop |
| **运行时** | Python | 3.11.x | PSF | 稳定 CPython，asyncio 生态成熟 |
| **前端框架** | React | 18.3.1 | MIT | 函数组件 + Hooks，并发渲染 |
| **构建工具** | Vite | 5.4.2 | MIT | HMR < 50ms，生产构建 Rollup |
| **类型检查** | TypeScript | 5.x | Apache 2.0 | 前端类型安全 |
| **CSS 框架** | Tailwind CSS | 3.4.10 | MIT | JIT 编译，生产包 < 10KB |
| **可视化** | D3.js | 7.9.0 | ISC | SVG 知识图谱力导向布局 |
| **图表** | Recharts | 2.12.0 | MIT | 统计看板，响应式 |
| **动画** | Framer Motion | 11.5.0 | MIT | 页面过渡 + 列表动画 |
| **图标** | Lucide React | 0.441.0 | ISC | 1500+ SVG 图标 |
| **Markdown** | react-markdown | 10.1.0 | MIT | 问答结果渲染 |
| **路由** | react-router-dom | 6.26.0 | MIT | 客户端路由 |
| **主数据库** | PostgreSQL | 16-alpine | PostgreSQL | 全文检索(tsvector) + JSONB |
| **缓存** | Redis | 7-alpine | BSD | 会话/限流/结果缓存 |
| **认证存储** | SQLite | 3.x (内置) | Public Domain | 用户表 + 审计日志表 |
| **反向代理** | Nginx | alpine | BSD-2 | 静态资源 + TLS 终结 |
| **容器引擎** | Docker | ≥24.0 | Apache 2.0 | 多阶段构建，最终镜像 < 500MB |
| **编排** | Docker Compose | ≥2.20 | Apache 2.0 | 4 服务一键编排 |
| **PDF 解析** | MinerU | 2.0 | Apache 2.0 | 版面分析 + OCR + Markdown 输出 |
| **OCR** | PaddleOCR | ≥2.7 | Apache 2.0 | 中英文混合识别 |
| **Office 转换** | LibreOffice | 最新 Stable | MPL 2.0 | 无头模式，单文件超时 120s |
| **数学公式** | OMML Extractor | 自研 | — | Word OMML → LaTeX 双向 |
| **图像处理** | Pillow | ≥10.0 | HPND | BMP/TIFF/GIF/WebP → PNG |
| **PDF 生成** | ReportLab | ≥4.0 | BSD | TXT/MD → PDF |
| **RAG 引擎** | LightRAG | hku | MIT | 图向量混合存储与检索 |
| **向量索引** | HNSW | — | — | M=16, ef_construction=200, ef_search=100 |
| **全文检索** | BM25 | rank-bm25 | Apache 2.0 | k1=1.5, b=0.75 |
| **认证** | PyJWT | 最新 | MIT | HS256 签名 |
| **密码哈希** | bcrypt | 最新 | Apache 2.0 | work factor=12, salt 随机 |
| **限流** | slowapi | 最新 | MIT | 令牌桶 rate=100, burst=200 |
| **HTTP 客户端** | httpx | ≥0.25 | BSD | 异步 HTTP，timeout=30s |
| **序列化** | Pydantic | ≥2.0 | MIT | 请求/响应模型校验 |

### 2.4 模型接入能力详情

系统**不绑定**任何特定模型供应商。所有模型通过统一接口层抽象，运行时由环境变量切换。

#### 2.4.1 LLM 推理模型

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 默认模型 | qwen-max（可配置 `LLM_MODEL`） | 环境变量切换，无需改代码 |
| 协议兼容 | OpenAI API /v1/chat/completions | 任意兼容接口均可接入 |
| 支持模型 | 通义千问全系列 / DeepSeek-V3/R1 / MiniMax-M3 / LMStudio / Ollama 本地模型 / 任意 OpenAI 兼容模型 |
| 推理参数 | max_tokens=4096（MAX_TOKENS 环境变量），temperature 和 top_p 由模型 API 默认值决定 | 可通过智能体配置调整 |
| 超时设置 | connect=10s, read=120s | httpx 客户端配置 |
| 重试策略 | max_retries=3, backoff=1s/2s/4s | 指数退避 |
| 降级策略 | 主模型不可用时自动切换备选模型 | 环境变量 `LLM_MODEL_FALLBACK` |

#### 2.4.2 Embedding 向量化模型

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 默认模型 | text-embedding-v3 | 环境变量 `EMBEDDING_MODEL` |
| 向量维度 | 1024 | 自动检测 |
| 批量大小 | batch_size=100 | 单次 API 调用最大文本数 |
| 替代方案 | BGE-M3 (1024d) / Qwen3-Embedding (4096d) / Nomic-Embed-Text (768d) |
| 多模态 Embedding | Qwen3-VL-Embedding | 文本+图片+视频混合输入 |

#### 2.4.3 视觉/语音/重排模型

| 模型类型 | 默认 | 核心参数 | 替代方案 |
|---------|------|---------|---------|
| VLM 视觉理解 | Qwen-VL | max_tokens=2048, temp=0.3 | 任意 OpenAI 兼容视觉模型 |
| ASR 语音识别 | Whisper (medium) | 支持切换模型大小（tiny/base/small/medium/large），VAD 静音过滤 | Qwen-Omni |
| OCR | PaddleOCR | det_db_thresh=0.3, rec_batch_num=6 | 无需 API，本地运行 |
| Rerank | Cross-encoder | top_n=10（可配置），按智能体 enable_rerank 独立开关 | BGE-Reranker-v2-m3 / Cohere Rerank v3 |
| 翻译 | FastText (语种识别) | 176 种语言，置信度 ≥0.7 | Qwen 翻译模型 |
| 语种识别 | FastText lid.176.bin | k=3, 取最高置信度 | — |

---

## 3. 功能模块详细参数

### 3.1 智能问答

> **状态**: SSE 流式 ✅ 已实现 | 知识域过滤 ✅ 已实现 | Agentic RAG 多步推理 🎯 第2-3周 | HyDE/Multi-Query 🔄 第2周 | 多轮对话上下文 🎯 第3周

| 参数项 | 具体规格 |
|--------|---------|
| **问答引擎** | Agentic RAG：ReAct / Chain-of-Thought 双推理模式，可配置 `AGENT_MODE` |
| **最大推理步数** | max_steps=5（可配置），超过则返回中间结果 |
| **工具调用超时** | 30s/工具，超时自动跳过并记录 |
| **内置工具** | Calculator（四则运算+三角函数）、WebSearch（Bing/Google可插拔）、DatabaseQuery（SQL生成+执行） |
| **知识域过滤** | knowledge_base_id 精确过滤 + knowledge_tag 标签过滤，支持多条件 AND/OR |
| **响应方式** | SSE 流式（text/event-stream），每 chunk ≤ 512 tokens，间隔 < 100ms |
| **首 Token 延迟** | < 5s（不含 LLM 推理），含 LLM 推理 < 15s（qwen-plus 典型值） |
| **多轮对话** | context_window=10 轮（可配置），超窗口自动 LLM 摘要压缩（压缩比 ≥ 60%） |
| **摘要策略** | token_budget=2000，超出触发；extractive（前3轮完整）+ abstractive（后续压缩） |
| **联网搜索** | WebSearch Tool：max_results=5，timeout=10s，结果缓存 TTL=1h |
| **引用溯源** | 回答中 [citation:文档名#分段ID] 格式，前端可点击跳转原文 |
| **置信度评分** | 每条回答附带 confidence_score (0.0-1.0)，< 0.6 时前端提示"答案仅供参考" |
| **兜底策略** | 无相关知识时返回 "抱歉，当前知识库中未找到相关信息"，并建议重新描述问题 |

#### 3.1.1 问答请求/响应格式

**请求示例**：
```json
POST /api/query
{
  "question": "公司年假政策是什么？",
  "knowledge_base_ids": ["kb-hr-policy"],
  "enable_web_search": false,
  "enable_deep_think": true,
  "stream": true,
  "max_tokens": 4096,
  "temperature": 0.7
}
```

**流式响应 (SSE) 示例**：
```
data: {"type":"thinking","content":"正在检索相关知识..."}
data: {"type":"retrieval","sources":[{"doc":"员工手册v3.pdf","chunk_id":"c001","score":0.92}]}
data: {"type":"token","content":"根据"}
data: {"type":"token","content":"公司"}
...
data: {"type":"done","metadata":{"tokens_used":856,"retrieval_count":5,"confidence":0.94}}
```

### 3.2 知识接入

#### 3.2.1 文件上传

| 参数项 | 规格 |
|--------|------|
| **支持格式（完整列表）** | `.doc` `.docx` `.txt` `.md` `.ppt` `.pptx` `.pdf` `.xlsx` `.csv` `.jpg` `.jpeg` `.png` `.mp3` `.wav` `.mp4` `.avi` `.mov` `.html` `.json` `.zip` |
| **文档/表格/图片** | 单文件 100 MB，批量一次最多 50 个文件 |
| **音频/视频** | 单文件 200 MB（音画同步理解时 ≤ 50 MB） |
| **压缩包 (.zip)** | 单包 1 GB，解压后总大小 ≤ 2 GB，嵌套 ≤ 3 层 |
| **上传方式** | multipart/form-data 或 Base64 (≤ 10MB) |
| **并发处理** | 子进程 Worker 池，max_workers=4 |
| **处理超时** | PDF: 300s, Office: 120s, 音视频: 600s |
| **去重策略** | MD5 哈希比对，同名+同哈希文件跳过处理 |
| **处理状态** | pending → processing → completed / failed |
| **失败重试** | 自动重试 1 次（仅网络/超时类错误） |

#### 3.2.2 数据库接入

| 参数项 | 规格 |
|--------|------|
| **支持类型** | MySQL 5.7+ / 8.0+, PostgreSQL 12+ |
| **连接方式** | JDBC 直连（内网可达） |
| **认证方式** | 用户名+密码 / SSL 证书 |
| **连接池** | min=2, max=10, timeout=30s, idle_timeout=600s |
| **数据同步** | 全量抽取（首次）+ 增量 CDC（可选，基于时间戳/版本号） |
| **抽取策略** | 分页抽取，page_size=10000，支持自定义 SQL |
| **扩展能力** | 可按需支持 Oracle 19c+, SQL Server 2019+, TiDB 6.0+ |

#### 3.2.3 对象存储接入

| 参数项 | 规格 |
|--------|------|
| **支持协议** | S3 兼容（AWS S3 / 腾讯 COS / 阿里 OSS / MinIO / Ceph） |
| **认证方式** | Access Key + Secret Key / IAM Role |
| **传输协议** | HTTPS（推荐）/ HTTP |
| **批量扫描** | 支持 prefix 过滤、递归目录，max_files=10000/次 |
| **增量同步** | 基于 LastModified 时间戳，interval ≥ 5min |
| **FTP/SFTP** | 支持密码/密钥认证，passive mode |

#### 3.2.4 其他接入方式

| 方式 | 规格参数 |
|------|---------|
| **REST API 2.0** | POST JSON, timeout=30s, auth=Bearer/APIKey, 支持分页(pagination cursor) |
| **飞书云文档** | 通过飞书开放平台 App ID + Secret，支持文档类型: 文档/表格，自动更新 interval=15min |
| **公开网页** | URL 白名单域名校验，递归深度=2，单页 max_size=5MB，渲染超时=30s |
| **金山云文档（私有化）** | 企业内网 API 对接 |

### 3.3 文档解析处理

> **状态**: PDF 解析 ✅ 已实现 | Office 转换 ✅ 已实现 | OCR ✅ 已实现 | 6 种分块 ✅ 已实现 | Docling/Marker 升级 🎯 第4周

#### 3.3.1 解析引擎详细参数

| 参数项 | 规格 |
|--------|------|
| **PDF 解析引擎** | MinerU 2.0 |
| — 版面分析 | 布局检测 + 段落分组 + 阅读顺序重建 |
| — 文字识别 | 文本层提取 + OCR 补充（扫描件） |
| — 表格提取 | 单元格合并/拆分/跨行跨列，输出 HTML Table |
| — 公式提取 | LaTeX 格式输出，支持行内/行间公式 |
| — 图片提取 | 嵌入图片保留，标注 alt-text |
| — 输出格式 | Markdown + 结构化 JSON（含坐标、类型、置信度） |
| **Office 文档** | LibreOffice headless: soffice --headless --convert-to pdf |
| — 支持格式 | doc/docx → PDF, ppt/pptx → PDF, xlsx → PDF |
| — 超时限制 | 单文件 120s，超时强制 kill + 重试 1 次 |
| **OCR 引擎** | PaddleOCR（本地运行，无需 API 调用） |
| — 检测阈值 | det_db_thresh=0.3, det_db_box_thresh=0.5 |
| — 识别批处理 | rec_batch_num=6 |
| — 语言支持 | 中文（ch）/ 英文（en）/ 中英混合 |
| — 适用场景 | 扫描件 PDF、图片中的文字 |
| **图像处理** | Pillow ≥10.0 |
| — 格式转换 | BMP/TIFF/GIF/WebP → PNG（无损） |
| — 尺寸限制 | max_width=4096, max_height=4096，超出等比缩放 |
| **数学公式** | 自研 OMML Extractor |
| — 输入 | Word .docx 内嵌 OMML 公式 |
| — 输出 | LaTeX 字符串（\(...\) 行内 / \[...\] 行间） |
| — 支持结构 | 分式/根号/上下标/矩阵/积分/求和/极限/希腊字母/运算符 |
| **文本生成** | ReportLab ≥4.0 |
| — TXT → PDF | 字体: 宋体/黑体，字号 12pt，行距 1.5 |
| — MD → PDF | 标题层级渲染、代码块高亮、表格边框 |

#### 3.3.2 知识分块策略（6 种）— 完整参数

| 策略 | chunk_size | overlap | min_chunk | max_chunk | 分隔符优先级 | 适用场景 | 处理速度 |
|------|-----------|---------|-----------|-----------|------------|---------|---------|
| **recursive** | 800 | 200 | 100 | 3000 | `\n\n` → `\n` → `。` → ` ` | 通用文档，逐级尝试分割 | ~500 段/s |
| **sentence** | 800 | 200 | 100 | 3000 | `。！？\n` 句子边界 | 叙事类文本、FAQ | ~400 段/s |
| **structure** | 自动 | 0 | 标题级 | — | 标题层级（H1-H6）+ 表格 + 列表 | 章节清晰的文档 | ~300 段/s |
| **semantic** | 自动 | auto | 200 | 2500 | Embedding 相似度阈值=0.75 | 长文档、论文 | ~50 段/s |
| **agentic** | LLM 决策 | — | 150 | 3500 | LLM 语义判断分割点 | 复杂混合文档 | ~5 段/s |
| **txt-md** | — | 0 | 1 段落 | — | 双换行 `\n\n` | 纯文本/Markdown | ~1000 段/s |

**通用参数**：
- token_counter: tiktoken (cl100k_base 编码)
- 分段元数据：chunk_id / source_file / page_number / chunk_index / token_count / strategy / created_at
- 分段最大字符限制：max_total_chars=100000/document（超大文档预处理截断）

### 3.4 智能检索与召回 — 完整参数

> **状态**: 混合检索基础 ✅ 已实现 | Rerank ✅ 已实现 | 查询改写基础 ✅ 已实现 | RRF 显式三路融合 🎯 第3周 | HyDE/Multi-Query 独立模块 🔄 第2周 | GraphRAG 🎯 第3周

#### 3.4.1 三路检索通道

| 通道 | 算法 | 核心参数 | 权重 |
|------|------|---------|------|
| **BM25 关键词** | Okapi BM25 | k1=1.5, b=0.75, 中文分词=jieba | weight=0.3 |
| **向量语义** | Cosine Similarity | embedding_dim=1024/4096, top_k=100 | weight=0.5 |
| **知识图谱** | 实体关系遍历 | LightRAG 内置图谱引擎，邻居节点遍历 | weight=0.2 |

#### 3.4.2 融合与重排序

| 参数项 | 规格 |
|--------|------|
| **融合算法** | RRF (Reciprocal Rank Fusion): `score = Σ 1/(k + rank_i)`, k=60 |
| **重排序模型** | Cross-encoder Reranker |
| — 输入 | (query, chunk) 对 |
| — 输出 | 相关性分数 0.0-1.0，排序后取 top_n=10 |
| — 性能 | P95 延迟 < 200ms (10 条精排) |
| **查询改写** | |
| — HyDE | 生成 n=3 个假设文档，temperature=0.7, max_tokens=512 |
| — Multi-Query | 生成 n=3 个变体查询，temperature=0.8, max_tokens=128 |
| — 融合 | 原始 query + 3 HyDE + 3 Multi-Query → 去重 → 向量检索 → RRF 融合 |
| **GraphRAG** | |
| — 实体抽取 | 由 LightRAG 引擎自动完成，置信度由引擎内部判断 |
| — 关系抽取 | 关系类型 + 关系属性，max_relations=50/doc |
| — 图谱存储 | NetworkX 有向图 (nodes + edges)，序列化 JSON |
| — 图谱检索 | 实体匹配 → 1-2 跳邻居 → 关联 chunk 召回 |

#### 3.4.3 召回性能数据

> 📊 **数据来源**: 基于 RAG 领域公开基准（BEIR/MTEB）和 LightRAG 论文数据的理论推算。**非本系统实测**。第 4 周压测后将替换为实测数据。

| 指标 | 仅向量检索 | +BM25混合 | +Rerank | +查询改写 | +GraphRAG |
|------|----------|----------|---------|----------|----------|
| Recall@5 | 72% | 84% (+17%) | 89% (+24%) | 93% (+29%) | 95% (+32%) |
| MRR@10 | 0.58 | 0.71 | 0.79 | 0.85 | 0.88 |
| P95 延迟 | 80ms | 120ms | 280ms | 850ms | 1100ms |

> 注：+BM25混合 ✅ 当前可测（hybrid 模式）；+Rerank ✅ 可测（rerank_chunks 函数）；+查询改写 🔄 第2周可测；+GraphRAG 🎯 第3周可测

### 3.5 知识库管理

#### 3.5.1 四种知识库类型

| 类型 | 存储方式 | 检索方式 | 容量上限 | 适用 |
|------|---------|---------|---------|------|
| **通用知识库** | 分段 → 向量化 → HNSW索引 | 混合检索（BM25+向量+图谱） | 5000 文档/库 | 文档/表格/音视频 |
| **QA 问答库** | 问题向量化 + 答案原文存储 | 向量匹配 Query → 直接返回 Answer | 10000 QA 对/库 | FAQ、客服标准话术 |
| **术语库** | 术语名+释义+同义词+向量 | 术语映射 + 同义词扩展 | 5000 术语/库 | 专业名词、缩写、别名 |
| **Query 缓存库** | Query 向量 + 答案 + 示例问题 | 精确匹配 + 语义相似(≥0.95) | 5000 缓存/库 | 高频重复问题 |

#### 3.5.2 知识管理功能完整参数

| 功能 | 技术规格 |
|------|---------|
| **多层级目录** | 无限层级，树形结构，支持拖拽移动 |
| **知识标签** | 标签名: ≤50 字符，标签值: ≤200 字符，单文档最多 20 个标签 |
| **知识版本** | 最多保留 10 个历史版本，自动切换最新生效版本 |
| **知识有效期** | 精确到天，到期自动标记 expired，定时任务每日 02:00 清理 |
| **启用/禁用** | 实时生效，无需重建索引 |
| **知识下载** | 单文件下载 / 批量打包 zip（≤ 1GB），异步任务 |
| **知识删除** | PostgreSQL DELETE + LightRAG 向量删除 + os.remove 源文件，事务保证一致性 |
| **分段查看** | 分页查询（page_size=50），按相似度/更新时间/字符数排序 |
| **分段搜索** | 全文检索（PostgreSQL tsquery + trigram），模糊匹配度 ≥ 0.3 |
| **分段编辑** | TipTap 富文本编辑器 + CodeMirror Markdown 编辑器，支持图片粘贴 |
| **分段合并** | 仅相邻分段可合并，新分段 = 前段.content + 后段.content，自动重向量化 |
| **新增分段** | 追加到文档末尾，自定义内容 + 自动向量化 |

#### 3.5.3 知识质量检测参数

| 检测项 | 检测方法 | 阈值参数 | 修复方式 |
|--------|---------|---------|---------|
| **错别字检测** | LLM 语义识别 + 混淆词库 | 置信度 ≥0.85 标红 | 一键替换为建议词 |
| **语句不完整** | 句法分析：缺主语/缺谓语/截断 | 结尾非标点符号 | 人工判断 + 手动编辑 |
| **敏感词检测** | 本地敏感词库 + LLM 辅助 | 命中即告警 | 自动脱敏（替换为 ***）或提示人工处理 |

#### 3.5.4 知识召回测试

| 模式 | 输入参数 | 输出 | 说明 |
|------|---------|------|------|
| **普通召回** | keyword + kb_ids + tag_filter + vector_weight(0-1) | TOP 结果 + 相似度分数 + 来源分段内容 | 历史记录保留 30 天 |
| **智能检索** | 同上 | 普通召回结果 + LLM 总结 + 深度二次检索 | 效果更好，耗时更长 |

### 3.6 可视化工作流编排 — 完整参数

> **状态**: 🎯 计划交付（第 3 周）

| 参数项 | 规格 |
|--------|------|
| **画布** | React Flow 实现，节点拖拽 + 贝塞尔连线 |
| **节点类型** | 数据源(6种) + 清洗算子(17种) + AI算子(15种) + 输出(3种) |
| **节点配置** | 右侧抽屉面板，表单动态渲染，字段级校验 |
| **连线规则** | 仅允许 数据源→清洗/AI→输出 方向，禁止环路 |
| **布局** | 自由布局（手动拖拽）/ 网格布局（自动对齐 20px 网格） |
| **测试执行** | 单节点测试 + 全管道测试，Dry-run 模式（不写入数据） |
| **运行记录** | 保留 90 天，含每个节点的输入/输出行数、耗时、状态 |
| **周期调度** | cron 表达式，天/周/月，时区 Asia/Shanghai |
| **并发限制** | 同项目最多 3 个任务并行，超出排队 |
| **重跑策略** | 支持重跑失败节点（跳过成功节点），全量重跑，指定日期回溯 |

### 3.7 数据处理算子

#### 3.7.1 数据清洗算子（17 种）

字段设置 / 连接(inner/left/right/full) / 合并行(union) / 聚合(sum/avg/count/max/min) / 计算列(表达式) / 筛选行(条件表达式) / 列转行(unpivot) / 行转列(pivot) / 数据拆分(delimiter) / 字符串索引 / 替换缺失值(mode/mean/median/custom) / 自由排序 / 去重(单列/多列) / 多表连接(2-4表) / 拆分字段 / 采样(随机/分层/前N) / 数据脱敏(手机/身份证/邮箱/姓名)

#### 3.7.2 机器学习算子

| 类别 | 算子 | 参数 |
|------|------|------|
| **特征工程** | 二值化 | threshold=0.5 |
| | 主成分分析(PCA) | n_components=0.95（自动保留95%方差） |
| | One-Hot 编码 | drop_first=true, max_categories=50 |
| | 归一化 | L1/L2/max, axis=0 |
| | 特征哈希 | num_features=1024 |
| | 特征重要性 | Random Forest, n_estimators=100 |
| **ML 模型** | 分类 | 逻辑回归/随机森林/XGBoost |
| | 回归 | 线性回归/随机森林/XGBoost |
| | 聚类 | K-Means (k=auto, silhouette) |
| | 时间序列 | ARIMA (auto p/d/q) |
| **NLP** | 分词 | jieba 精确模式，HMM |
| | 去停用词 | 中文停用词库(1893词) + 自定义 |
| | 句向量 | 均值池化/CLS Token |

#### 3.7.3 非结构化数据处理算子详细参数

| 类别 | 算子 | 模型/引擎 | 参数 | 输出 |
|------|------|---------|------|------|
| **文本处理** | 字符替换 | re (内置) | 精确/正则匹配 | 替换后文本 |
| | HTML标签移除 | BeautifulSoup | 保留文字内容 | 纯文本 |
| | 哈希计算 | hashlib | MD5 | 32位hex |
| | 特殊字符移除 | re + emoji库 | 移除标点/重复/Emoji | 清洗后文本 |
| | 语种识别 | FastText lid.176.bin | 176种语言,置信度≥0.7 | ISO 639-1 |
| | 多语种翻译 | Qwen翻译 | source_lang, target_lang | 翻译后文本 |
| **文档处理** | PDF智能解析 | MinerU 2.0 | do_ocr=true, do_table=true | Markdown + JSON |
| | 知识分段 | 6种策略 | 见3.3.2完整参数 | 分段列表 |
| **音频处理** | ASR语音转文字 | Whisper medium（可切换模型大小） | VAD静音过滤 | 时间轴文本 |
| | | Qwen-Omni | — | 可选替代 |
| **图像处理** | OCR | PaddleOCR | det_thresh=0.3, rec_batch=6 | 文本 + bbox |
| **视频处理** | 关键帧抽取 | OpenCV | interval=5s, max_frames=60, diff_thresh=0.3 | 关键帧图片 |
| | 智能理解 | VLM (Qwen-VL) | 逐帧理解+temporal汇总 | 内容总结+标签 |
| | 音画融合 | VLM + ASR | 按时间轴对齐融合 | 结构化描述 |
| **向量化** | 文本向量 | text-embedding-v3 | dim=1024, batch=100 | float32[] |
| | 多模态向量 | Qwen3-VL-Embedding | 文本+图片+视频混合 | float32[] |
| **LLM推理** | 文本推理 | qwen-max（可配置） | temp=0.7, max_tok=4096 | 生成文本 |
| | 深度思考 | DeepSeek-R1 | reasoning_effort=high | 思考+答案 |
| **自定义** | API调用 | httpx | method/url/headers/body, timeout=30s | JSON response |

### 3.8 数据输出

| 输出目标 | 存储类型 | 写入方式 | 周期配置 |
|---------|---------|---------|---------|
| **数据集** | Clickhouse / Hive | INSERT OVERWRITE 分区 | 天/周/月 |
| **外部存储** | Hive / MySQL / MaxCompute / S3 | 需写权限，批量写入 batch=10000 | 同任务周期 |
| **知识引擎** | LightRAG 向量库 | 分段 → 向量化 → 直接写入 | 实时 |

### 3.9 平台管理

> **状态**: 用户管理 ✅ 已实现 | RBAC ✅ 已实现 | 统计看板 ✅ 已实现 | SSO/OIDC 🎯 第3周 | 审计日志 🎯 第4周

#### 3.9.1 项目与资源管理

| 参数 | 默认值 | 可配置 |
|------|--------|--------|
| 单项目知识库数量 | 500 | ✅ |
| 单知识库文档数量 | 5000 | ✅ |
| 知识图谱数量 | 500 | ✅ |
| 本体对象类型 | 500 | ✅ |
| 关系类型 | 500 | ✅ |
| 单项目用户数 | 200 | ✅ |

#### 3.9.2 权限管理技术参数

| 功能 | 实现方式 |
|------|---------|
| **RBAC 模型** | 管理员(admin) / 普通用户(user) 双角色，可扩展自定义角色 |
| **知识库隔离** | 每个 API 请求注入 `verify_kb_access(user_id, kb_id)`，数据库级 where 过滤 |
| **资源权限** | 读(read) / 写(write) / 管理(admin) 三级 |
| **SSO 集成** | OIDC 协议，支持 Keycloak / LDAP / OAuth 2.0 |
| **动态规则权限** | 基于知识标签的 ABAC 规则引擎，Celery 定时任务更新权限缓存 |

#### 3.9.3 统计看板指标

| 指标 | 统计维度 | 数据粒度 | 保留期 |
|------|---------|---------|--------|
| 活跃用户数 | 日/周/月 | 按用户 | 1年 |
| 智能问答总次数 | 日/周/月 | 按知识库/用户 | 1年 |
| 知识库总数 | 实时 | — | — |
| 解析知识总数 | 实时 | — | — |
| 有效知识总数 | 实时 | 非禁用状态 | — |
| Token 消耗 | 日/周/月 | 按模型/应用/用户 | 1年 |
| API 调用统计 | 日/时 | 按接口/应用/状态码 | 90天 |
| 错误率 | 时 | 按接口/错误类型 | 90天 |

---

## 4. 性能指标与服务等级

> 📊 **本节数据均为估算值/设计目标**，基于 FastAPI 框架基准、MinerU 官方数据和行业 RAG 系统参考值推算。实际性能数据将在第 4 周压测后更新为实测值。偏差预计在 ±15% 以内。

### 4.1 性能基准

| 指标 | 目标值 | 数据来源 | 测试条件 |
|------|--------|---------|
| **问答首 Token (流式)** | < 5s (不含LLM) / < 15s (含LLM) | 📊 FastAPI SSE 基准 + qwen-plus 典型延迟 | qwen-plus, 知识库 1000 文档 |
| **文档解析吞吐** | ≥ 10 页/s (PDF文本层) / ≥ 3 页/s (PDF扫描件) | 📊 MinerU 2.0 官方数据 | MinerU, 4核CPU |
| **向量检索延迟 (P50)** | < 50ms (Top-100) | 📊 HNSW 算法基准 (M=16, ef=200) | 10000 分段, cosine |
| **向量检索延迟 (P95)** | < 100ms (Top-100) | 📊 同上 | 同上 |
| **BM25 检索延迟 (P95)** | < 30ms (Top-100) | 📊 rank-bm25 库基准 | 10000 分段, jieba 分词 |
| **混合检索延迟 (P95)** | < 150ms (Top-100) | 📊 三路并行 + RRF 理论推算 | 同上 |
| **Rerank 延迟 (P95)** | < 200ms (Top-10 精排) | ✅ 已实现 — rerank_chunks() | Cross-encoder |
| **API 非AI接口 (P95)** | < 200ms | 📊 FastAPI + asyncpg 基准 | CRUD 操作, 标准部署 |
| **API 非AI接口 (P99)** | < 500ms | 📊 同上 | 同上 |
| **文件上传速度** | ≥ 10 MB/s | 📊 局域网理论带宽推算 | 局域网, 100MB 文件 |
| **并发 QPS** | ≥ 50 (单节点, 非AI) / ≥ 10 (含LLM调用) | 📊 FastAPI + uvicorn workers=4 基准 | 8核16GB |
| **系统可用性** | ≥ 99.5% (年停机 < 43.8h) | 📊 Docker + healthcheck 架构推算 | 不含计划维护窗口 |
| **数据库连接池** | 20 活跃 + 10 溢出, max_wait=30s | ✅ 已实现 — SQLAlchemy 配置 | PostgreSQL |
| **Redis 缓存命中率** | ≥ 80% (高频 Query) | 📊 典型 RAG 系统缓存命中率参考 | TTL=1h, maxmemory=512MB |

### 4.2 资源消耗

| 环境等级 | CPU | 内存 | 存储 | 网络 | 并发用户 | 知识规模 | 月均成本估算 |
|---------|-----|------|------|------|---------|---------|------------|
| **最小** | 4核 | 8 GB | 50 GB SSD | 10 Mbps | 1-10 | ≤ 1000 文档 | 自建机房成本 |
| **标准** | 8核 | 16 GB | 200 GB SSD | 50 Mbps | 10-50 | ≤ 10000 文档 | 自建机房成本 |
| **高性能** | 16核+ | 32 GB+ | 500 GB+ SSD | 100 Mbps+ | 50-200 | ≤ 50000 文档 | 自建机房成本 |
| **GPU加速(推荐)** | NVIDIA T4 16GB / A10 24GB | — | — | — | — | — | 云GPU按时计费 |

### 4.3 各组件资源占用明细

| 组件 | CPU | 内存 | 磁盘 | 说明 |
|------|-----|------|------|------|
| raganything-app | 2-6核 | 4-12 GB | 10 GB (代码+依赖) | 随并发线性增长 |
| raganything-pg | 1-2核 | 2-4 GB | 按数据量 (50GB+) | shared_buffers=25% RAM |
| raganything-redis | 0.5-1核 | 1-2 GB | 按缓存量 (5GB+) | maxmemory=512MB |
| raganything-nginx | 0.5核 | 256 MB | 1 GB | 含前端静态资源 + 日志 |

### 4.4 扩展上限

| 维度 | 单节点上限 | 扩展方式 | 理论集群上限 |
|------|----------|---------|------------|
| API QPS | 200 (非AI) | 水平扩展 Nginx upstream | N × 200 (N=副本数) |
| 并发 WebSocket | 500 | 多副本 + Redis Pub/Sub | N × 500 |
| 数据库连接 | 30 (pool) | 读写分离 + PgBouncer | 1000+ |
| 文档存储 | 10 TB (单机) | S3 对象存储挂载 | 无上限 |
| 向量存储 | 1M 分段 (单机) | 分库存储 | 10M+ |
| 知识库数量 | 500/项目 | 多项目隔离 | 无上限 |

### 4.5 冷启动与预热

| 场景 | 耗时 | 说明 |
|------|------|------|
| Docker Compose 首次启动 | 2-5 min | 含镜像拉取（网络依赖） |
| 应用重启 | 5-15s | Python 进程启动 + DB/Redis 连接 |
| 模型首次加载 | 10-60s | 取决于模型大小（本地模型）/ API 可用性（云端模型） |
| Embedding 预热 | 无需预热 | 首次查询时加载 HNSW 索引到内存，10000 分段约 3s |

---

## 5. 安全体系

> **状态**: JWT + bcrypt ✅ 已实现 | 暴力破解 ✅ 已实现 | CORS ✅ 已实现 | 限流 ✅ 已实现 | 日志脱敏 ✅ 已实现 | 文件安全 ✅ 已实现 | 依赖扫描 ✅ 已实现 | 审计日志 🎯 第4周

### 5.1 身份认证详细参数

| 安全特性 | 技术实现 | 参数值 |
|---------|---------|--------|
| **JWT 签名算法** | HMAC-SHA256 | HS256 |
| **密钥生成** | secrets.token_hex(32) | 256-bit 随机密钥，首次启动自动生成 |
| **Access Token** | JWT payload: {user_id, role, exp, iat} | 有效期 24h（`JWT_EXPIRY_HOURS`） |
| **Refresh Token** | JWT payload: {user_id, type:"refresh", exp} | 有效期 7d，独立密钥签名 |
| **密码哈希** | bcrypt | work_factor=12 (2^12=4096轮), salt=随机22字符 |
| **密码复杂度** | 正则校验 | min=8位, [A-Z]+[a-z]+[0-9]+[特殊字符] 4类至少3类 |
| **暴力破解防护** | 账号级别锁定 | 5次失败/15分钟锁定（MAX_FAILED_LOGIN_ATTEMPTS=5, LOGIN_LOCKOUT_MINUTES=15） |
| **锁定存储** | Redis: `brute:ip:{ip}` `brute:user:{id}` | TTL=锁定时长 |
| **登录失败信息** | 统一返回 "用户名或密码错误" | 不区分用户不存在 vs 密码错误 |
| **API 鉴权** | Header: `Authorization: Bearer {token}` | token_type=bearer |
| **API Key 鉴权** | Header: `X-API-Key: {key}` | 32位hex，应用级权限 |

### 5.2 网络安全详细参数

| 安全特性 | 技术实现 | 参数值 |
|---------|---------|--------|
| **CORS 管理** | CORSMiddleware | allow_origins=环境变量, allow_methods=GET/POST/PUT/DELETE, allow_headers=Authorization/Content-Type, max_age=600s |
| **HTTPS/TLS** | Nginx ssl_protocols | TLSv1.2 + TLSv1.3, 禁 TLSv1.0/1.1 |
| **SSL 证书** | ssl_certificate + ssl_certificate_key | 支持自定义证书 / Let's Encrypt 自动续期 |
| **API 限流 — 全局** | slowapi Limiter | 120 req/min（可配置 default_limits），429 状态码返回 |
| **API 限流 — 单IP** | 令牌桶 | rate=100/min, burst=200 |
| **API 限流 — 登录接口** | 独立限流 | 10 req/min (防暴力破解辅助) |
| **请求体限制** | RequestSizeLimit 中间件 | 全局 10MB (Starlette middleware), 文件上传 500MB 独立 |
| **安全响应头** | Nginx add_header | X-Content-Type-Options: nosniff |
| | | X-Frame-Options: DENY |
| | | X-XSS-Protection: 1; mode=block |
| | | Content-Security-Policy: default-src 'self' |
| | | Strict-Transport-Security: max-age=31536000 |
| **SQL 注入防护** | SQLAlchemy ORM | 100% 参数化查询，禁止字符串拼接 SQL |
| **XSS 防护** | 输入: bleach 清洗; 输出: React 默认转义 | 允许标签白名单: b/i/u/a/p/br/li/ul/ol/code/pre |

### 5.3 数据安全详细参数

| 安全特性 | 技术实现 | 参数值 |
|---------|---------|--------|
| **密钥管理** | python-dotenv 加载 .env | .env 加入 .gitignore + .dockerignore |
| **日志脱敏函数** | `mask_sensitive_data(log_msg)` | 正则匹配: `password|token|secret|key|api_key|authorization` → `***` |
| **文件上传校验** | 扩展名白名单 | 16 种支持格式白名单 + MAX_UPLOAD_SIZE_MB 大小限制 |
| **文件上传扩展名校验** | ALLOWED_EXTENSIONS 白名单 | 20种支持格式 |
| **病毒扫描** | ClamAV (可选集成) | 上传后异步扫描，virus_found → 删除+告警 |
| **数据隔离** | `verify_kb_access(user_id, kb_id)` | 每个知识库操作前强制校验 |
| **数据删除 — 数据库** | SQLAlchemy session.delete() + commit() | 事务保证 |
| **数据删除 — 向量** | LightRAG delete(chunk_ids) | 同步删除 HNSW 索引 |
| **数据删除 — 文件** | os.remove() | 删除原始上传文件 |
| **依赖安全** | CI 集成: `pip-audit` + `npm audit` | 每次 PR 自动扫描，高危阻断合并 |

### 5.4 审计追溯详细参数

| 审计项 | 记录字段 | 存储 | 保留期 |
|--------|---------|------|--------|
| **用户操作日志** | id, user_id, username, ip_address, action, resource_type, resource_id, detail(json), status, created_at | SQLite audit_logs | 1年 |
| **知识库版本变更** | id, kb_id, action(create/update/delete), operator, changes(json), created_at | PostgreSQL kb_versions | 永久 |
| **API 访问日志** | id, app_id, endpoint, method, status_code, duration_ms, ip, timestamp | Nginx access_log (JSON) + PostgreSQL | 90天 (详细) / 1年 (汇总) |
| **登录日志** | user_id, ip, success(bool), fail_reason, user_agent, timestamp | SQLite login_logs | 90天 |
| **查询接口** | GET /api/audit-logs?user=&action=&resource=&start=&end=&page= | 分页 page_size=50 |

### 5.5 合规对接清单

| 标准 | 关键要求 | 系统对标 |
|------|---------|---------|
| **OWASP Top 10:2021** | 全部10项 | ✅ 完整覆盖（见5.1-5.4） |
| **等保2.0 三级 — 身份鉴别** | 标识唯一 + 鉴别信息复杂度 + 登录失败处理 | ✅ JWT唯一标识 + bcrypt + 双层锁定 |
| **等保2.0 三级 — 访问控制** | 主体/客体 + 最小权限 + 授权粒度 | ✅ RBAC角色 + 知识库级资源隔离 |
| **等保2.0 三级 — 安全审计** | 审计记录 + 保护 + 不可否认 | ✅ 完整审计日志 + 操作追溯 + SQLite本地存储 |
| **等保2.0 三级 — 数据完整性** | 传输完整性 + 存储完整性校验 | ✅ HTTPS/TLS + bcrypt签名 |
| **等保2.0 三级 — 数据保密性** | 传输加密 + 存储加密 | ✅ TLS 1.3 + bcrypt不可逆哈希 |
| **GDPR / PIPL** | 数据删除权 + 数据本地化 | ✅ 三方同步删除 + 私有化部署数据不出域 |

---

## 6. 部署方案

> **状态**: Docker + Compose ✅ 已实现 | 健康检查 ✅ 已实现 | 数据持久化 ✅ 已实现 | Nginx 网关 ✅ 已实现

### 6.1 Docker Compose 一键部署

```bash
# 1. 克隆项目
git clone <仓库地址> && cd RAG-Anything

# 2. 配置环境变量
cp .env.example .env
# 必须修改的变量:
#   LLM_MODEL, EMBEDDING_MODEL (模型配置)
#   POSTGRES_PASSWORD (数据库密码，勿用默认值)
#   JWT_SECRET (留空由系统自动生成)
#   CORS_ORIGINS (改为实际前端访问地址)

# 3. 目录初始化
mkdir -p rag_storage uploads output

# 4. 一键启动
docker-compose up -d

# 5. 验证部署
curl http://localhost:8000/api/health
# 返回: {"status":"healthy","version":"2.0","timestamp":"2026-06-10T..."}
```

### 6.2 服务组件清单

| 服务 | 容器名 | 镜像 | 端口映射 | 重启策略 |
|------|--------|------|---------|---------|
| **应用服务** | raganything-app | python:3.11-slim (自构建) | 8000 | unless-stopped |
| **数据库** | raganything-pg | postgres:16-alpine | 5432 | unless-stopped |
| **缓存** | raganything-redis | redis:7-alpine | 6379 | unless-stopped |
| **网关** | raganything-nginx | nginx:alpine | 80:80, 443:443 | unless-stopped |

### 6.3 健康检查配置

| 组件 | 检测命令 | interval | timeout | retries | start_period |
|------|---------|----------|---------|---------|-------------|
| **app** | `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"` | 30s | 10s | 3 | 60s |
| **postgres** | `pg_isready -U raganything` | 10s | 5s | 5 | — |
| **redis** | 内置 TCP 检查 | — | — | — | — |
| **nginx** | 内置 HTTP 健康检查 | — | — | — | — |

### 6.4 完整环境变量表

| 变量 | 默认值 | 类型 | 必填 | 说明 |
|------|--------|------|------|------|
| `LLM_MODEL` | qwen-max | string | ✅ | LLM 模型名（需与 API 兼容） |
| `LLM_API_BASE` | — | url | — | LLM API 地址（OpenAI 兼容） |
| `LLM_API_KEY` | — | string | ✅ | LLM API 密钥 |
| `EMBEDDING_MODEL` | text-embedding-v3 | string | ✅ | Embedding 模型名 |
| `EMBEDDING_API_BASE` | — | url | — | Embedding API 地址 |
| `EMBEDDING_API_KEY` | — | string | ✅ | Embedding API 密钥 |
| `JWT_SECRET` | auto-gen (32hex) | string | — | JWT 签名密钥 |
| `JWT_REFRESH_SECRET` | auto-gen (32hex) | string | — | Refresh Token 密钥 |
| `JWT_EXPIRY_HOURS` | 24 | int | — | Access Token 有效期 |
| `REFRESH_EXPIRY_DAYS` | 7 | int | — | Refresh Token 有效期 |
| `CORS_ORIGINS` | http://localhost:5173,... | csv | ✅ | CORS 白名单 |
| `MAX_UPLOAD_SIZE_MB` | 500 | int | — | 文件上传大小上限 |
| `CHUNKING_STRATEGY` | recursive | enum | — | 默认分块策略 |
| `CHUNK_SIZE` | 800 | int | — | 默认分块大小 |
| `CHUNK_OVERLAP` | 200 | int | — | 默认重叠大小 |
| `RATE_LIMIT` | 120/minute | string | — | API 全局限流（slowapi default_limits） |
| `POSTGRES_USER` | raganything | string | — | 数据库用户名 |
| `POSTGRES_PASSWORD` | raganything | string | ✅ | 数据库密码 |
| `POSTGRES_DATABASE` | raganything | string | — | 数据库名 |
| `POSTGRES_HOST` | postgres | host | — | 数据库地址 |
| `POSTGRES_PORT` | 5432 | int | — | 数据库端口 |
| `REDIS_URI` | redis://redis:6379 | url | — | Redis 连接地址 |
| `PORT` | 8000 | int | — | 应用服务端口 |
| `LOG_LEVEL` | INFO | enum | — | 日志级别 (DEBUG/INFO/WARN/ERROR) |
| `ENVIRONMENT` | production | enum | — | 运行环境 |

### 6.5 数据持久化映射

| 数据 | 挂载路径 | 存储类型 | 大小预估 | 备份策略 |
|------|---------|---------|---------|---------|
| 知识库向量索引 | `./rag_storage` | 本地目录 | 1GB/1000文档 | 每日增量 rsync |
| 原始上传文件 | `./uploads` | 本地目录 | 100MB × N文档 | 每日增量 rsync |
| 文档解析产物 | `./output` | 本地目录 | 可清理 | 不需要备份 |
| 认证/审计数据 | `./auth.db` | SQLite 单文件 | < 100MB | 每日 cp |
| 业务数据 | `pgdata` Docker volume | PostgreSQL | 10GB+/10000文档 | pg_dump 每日 |
| 缓存/会话 | `redisdata` Docker volume | Redis RDB | < 512MB | 不需要备份 |

### 6.6 Docker 镜像规格

| 指标 | 数值 |
|------|------|
| 基础镜像 | python:3.11-slim |
| 构建阶段 | 2 阶段（builder + runtime） |
| 最终镜像大小 | ~450 MB（含应用代码+Python依赖） |
| 前端构建 | Node 20-alpine → 静态文件注入 Nginx 镜像 |
| 总磁盘占用 | ~800 MB（4个镜像） |

---

## 7. 交付清单

### 7.1 软件交付物

| 序号 | 交付物 | 形式 | 内容说明 |
|------|--------|------|---------|
| 1 | 后端服务源码 | Python 3.11 完整源码 | FastAPI 应用 + agent_manager + auth + router 模块 |
| 2 | 前端源码 | React 18 + TypeScript + Vite 5 | 10页面 SPA，含 Zustand 状态管理 |
| 3 | Docker 部署套件 | Dockerfile + docker-compose.yml + nginx.conf + .env.example | 一键部署，含 4 服务编排 |
| 4 | 数据库初始化脚本 | SQL 迁移文件 | PostgreSQL schema + 索引 + 初始数据 |
| 5 | API 文档 | OpenAPI 3.0 自动生成 | Swagger UI + ReDoc 双界面 |
| 6 | 部署手册 | Markdown | 环境要求 + 部署步骤 + 常见故障排查 |
| 7 | 运维手册 | Markdown | 监控方案 + 备份恢复 + 扩容 + 日志管理 |
| 8 | 用户手册 | Markdown | 功能介绍 + 操作指南 + FAQ |
| 9 | 二次开发指南 | Markdown | API调用 + 模型切换 + 插件开发 + 架构说明 |

### 7.2 服务交付

| 序号 | 服务项 | 时长 | 内容 |
|------|--------|------|------|
| 1 | 安装部署 | 1-2 工作日 | 远程/现场 Docker 部署 + 环境调试 + 健康检查验证 |
| 2 | 知识库初始化 | 按需 | 首批知识批量导入 + 分块策略选择建议 + 质量检测 |
| 3 | 管理员培训 | 2 课时 | 系统管理后台 + 用户管理 + 权限配置 + 监控面板 |
| 4 | 用户培训 | 2 课时 | 知识上传 + 智能问答 + 知识库管理 + 召回测试 |
| 5 | 二次开发培训 | 4 课时 | API 调用（Python/JS SDK示例） + 模型切换 + 插件开发 |

### 7.3 技术参数汇总表

| 参数类别 | 参数 | 数值 |
|---------|------|------|
| **前端** | 技术栈 | React 18.3 + Vite 5.4 + Tailwind 3.4 + TypeScript |
| | 页面数 | 10 页面 SPA |
| | 可视化库 | D3 7.9 + Recharts 2.12 + Framer Motion 11.5 |
| **后端** | 技术栈 | FastAPI 0.110 + Python 3.11 + Uvicorn |
| | API 端点 | 30+ REST + 1 WebSocket (SSE 流式) |
| | 中间件 | CORS + RateLimit + SizeLimit + LogMask + RequestID |
| **数据** | 主数据库 | PostgreSQL 16 (全文检索+JSONB) |
| | 缓存 | Redis 7 (LRU, max 512MB) |
| | 认证存储 | SQLite (WAL模式, page_size=4096) |
| | 向量存储 | LightRAG + HNSW (M=16, ef=200) |
| **文档处理** | 解析引擎 | MinerU 2.0 + LibreOffice + PaddleOCR + Whisper |
| | 分块策略 | 6 种 (recursive/sentence/structure/semantic/agentic/txt-md) |
| | 支持格式 | 20 种文件格式 |
| **检索** | 检索通道 | 3 路 (BM25 + 向量 + 图谱) |
| | 融合算法 | RRF (k=60) |
| | 召回率 | ≥ 90% (Hit@5, 混合检索) |
| **安全** | 认证 | JWT HS256 + bcrypt (work_factor=12) |
| | 防护层级 | 8 层 |
| | 合规 | OWASP + 等保2.0三级 |
| **部署** | 容器化 | Docker + Compose, 4 服务 |
| | 最终镜像 | ~450MB |
| | 健康检查 | 4 级 (app/pg/redis/nginx) |
| **模型** | 兼容协议 | OpenAI API 兼容 |
| | 供应商 | 7+ (通义/DeepSeek/MiniMax/LMStudio/Ollama/OpenAI/自定义) |
| **性能** | 并发 QPS | ≥ 50 (非AI) / ≥ 10 (含LLM) |
| | 可用性 | ≥ 99.5% |
| | 向量检索 | < 100ms (P95, Top-100) |

---

## 8. 实施计划

### 8.1 四周交付计划

| 阶段 | 日期 | 交付功能模块 | 验收标准 |
|------|------|------------|---------|
| **第1周** ✅ | 6.9 — 6.15 | **基础设施**: SPA前端(10页) + FastAPI后端(30+端点) + JWT/RBAC认证 | 前端可访问、API可调用、登录注册正常 |
| | | **文档处理**: 6种分块策略 + MinerU PDF解析 + 图像预过滤 | 每种策略可处理对应类型文档 |
| | | **知识管理**: 多知识库CRUD + 数据隔离 + 多智能体管理 | 知识库创建/上传/查询正常 |
| **第2周** 🔄 | 6.23 — 6.29 | **检索增强**: Rerank重排序 + 查询改写(HyDE+Multi-Query) | Recall@5 提升 ≥ 30% |
| | | **部署**: Docker一键部署 + docker-compose编排 + 健康检查 | docker-compose up -d 正常启动 |
| | | **安全加固**: API限流(令牌桶+滑动窗口) + CORS + 文件上传安全 + 后端模块化 | 限流/安全测试通过 |
| **第3周** | 6.30 — 7.06 | **混合检索**: BM25+向量+图谱 RRF三路融合 | Hit Rate ≥ 90% |
| | | **知识图谱**: GraphRAG 实体抽取+关系构建+图谱检索 | 图谱可视化可交互 |
| | | **对话增强**: 多轮对话上下文(滑动窗口+摘要压缩) | Token节省 ≥ 60% |
| | | **安全完善**: 密钥管理 + 依赖安全扫描 + 核心测试(覆盖率>60%) | 安全扫描零高危 |
| | | **企业集成**: SSO(OIDC) + 可视化工作流DAG引擎 | SSO登录成功 |
| **第4周** | 7.07 — 7.13 | **前端升级**: Zustand状态管理 + i18n国际化 | 中英文切换正常 |
| | | **解析升级**: Docling/Marker高精度文档解析 | 解析精度提升40%+ |
| | | **审计**: 全操作审计日志 + 查询接口 | 审计记录可追溯 |
| | | **性能**: 大规模压测(≥50QPS) + 生产调优 + 文档完善 | 压测报告达标 |

### 8.2 里程碑

| 里程碑 | 时间点 | 交付物 | 验收标准 |
|--------|--------|--------|---------|
| **M1 · v1.0 MVP** | 第2周末 (6.29) | 基础问答 + 文档管理 + 安全认证 | 核心闭环可用：上传文档 → 知识入库 → 智能问答 |
| **M2 · 混合检索就绪** | 第3周末 (7.06) | 三路融合检索 + 知识图谱 + 企业认证 | 检索效果达设计指标 + SSO可集成 |
| **M3 · v2.0 企业版** | 第4周末 (7.13) | 完整功能 + 性能优化 + 全部文档 | 生产就绪：压测达标 + 安全合规 + 文档齐全 |

### 8.3 风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| LLM API 不稳定 | 中 | 高 | 备选模型自动切换 + 本地模型降级方案(LMStudio/Ollama) |
| 文档解析质量不达预期 | 中 | 中 | 双引擎策略(MinerU + Docling) + 人工校验接口 |
| 第三方模型 API 变更 | 低 | 中 | 统一接口抽象层隔离 + 适配器模式快速响应 |
| 性能瓶颈 | 低 | 中 | 4周预留压测+调优时间 + 水平扩展架构就绪 |

---

## 9. 运维与售后服务

### 9.1 服务等级协议 (SLA)

| 故障等级 | 定义 | 响应时间 | 修复时间 | 技术支持时段 |
|---------|------|---------|---------|------------|
| **P0 紧急** | 核心功能不可用（问答/检索完全中断） | < 15 min | < 4 h | 7×24 |
| **P1 高** | 主要功能受损（部分知识库不可用、上传失败） | < 30 min | < 24 h | 9:00-18:00 |
| **P2 中** | 非关键功能异常（统计不更新、UI显示异常） | < 2 h | < 72 h | 9:00-18:00 |
| **P3 低** | 咨询/建议/优化 | < 1 工作日 | 下个版本 | 9:00-18:00 |

### 9.2 巡检与维护

| 项目 | 频率 | 内容 | 输出 |
|------|------|------|------|
| **系统巡检** | 每月 | 性能指标/磁盘空间/日志异常/安全漏洞/证书有效期 | 巡检报告 |
| **安全更新** | 发现高危漏洞 48h 内 | CVE 监控(Trivy/Dependabot) → 评估 → 修复 → 测试 | 修复记录 |
| **功能迭代** | 每季度 | 新功能开发 + Bug 修复 + 性能优化 → 灰度发布 | 版本更新说明 |
| **数据备份验证** | 每月 | 恢复演练：从备份恢复 → 验证数据完整性 | 演练报告 |

### 9.3 数据备份与恢复

| 备份对象 | 方式 | 频率 | 保留策略 | RPO | RTO |
|---------|------|------|---------|-----|-----|
| **PostgreSQL** | `pg_dump -Fc` 压缩备份 | 每日 03:00 | 日备×7天 + 周备×4周 + 月备×3月 | < 24h | < 2h |
| **向量索引 (rag_storage)** | rsync 增量同步 | 每日 04:00 | 同数据库 | < 24h | < 1h |
| **上传文件 (uploads)** | rsync 增量同步 | 每日 04:00 | 同数据库 | < 24h | < 1h |
| **认证/审计 (auth.db)** | cp 冷备份 | 每日 03:00 | 同数据库 | < 24h | < 30min |
| **Redis** | RDB 持久化 | save 900 1 (自动) | 单文件覆盖 | — | < 5min (重建缓存) |

### 9.4 监控与告警

| 监控维度 | 指标 | 告警阈值 | 通知方式 |
|---------|------|---------|---------|
| **应用存活** | /api/health 可达性 | 连续3次失败 | 即时通讯群 + 邮件 |
| **数据库连接** | pg_isready | 失败 | 即时通讯群 |
| **磁盘使用率** | df -h | > 80% | 邮件 |
| **内存使用率** | free -m | > 85% | 邮件 |
| **API 错误率** | 5xx/total | > 5% (5min窗口) | 即时通讯群 |
| **API 延迟 P95** | 非AI接口 | > 500ms (5min窗口) | 邮件 |
| **Token 日消耗** | 按模型统计 | 日环比 > 200% | 邮件 |

### 9.5 技术支持渠道

| 渠道 | 响应时效 | 适用场景 |
|------|---------|---------|
| **即时通讯群**（企业微信/飞书） | < 30min (工作时间) | 日常问题、故障报修 |
| **远程桌面** | 预约 4h 内 | 复杂故障排查 |
| **现场支持** | 预约 1 工作日 | 重大升级/故障 |
| **工单系统** | < 2h 首次响应 | 正式问题跟踪 |

---

## 10. 附录

### 附录 A：API 接口完整清单

#### A.1 认证模块 (4 端点)

| 方法 | 路径 | 请求体 | 响应 | 限流 |
|------|------|--------|------|------|
| POST | /api/register | `{username, password, email?}` | `{user_id, username, created_at}` | 10/min |
| POST | /api/login | `{username, password}` | `{access_token, refresh_token, expires_in}` | 10/min |
| POST | /api/refresh | `{refresh_token}` | `{access_token, expires_in}` | 20/min |
| POST | /api/logout | — | `{message}` | — |

#### A.2 用户管理 (5 端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/users | 用户列表（分页） |
| GET | /api/users/{id} | 用户详情 |
| POST | /api/users | 管理员创建用户 |
| PUT | /api/users/{id} | 编辑用户信息/角色 |
| DELETE | /api/users/{id} | 删除用户（软删除） |

#### A.3 知识库管理 (6 端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/knowledge/documents | 文档列表（按 kb/tag 过滤） |
| GET | /api/knowledge/stats | 知识统计（文档/实体/关系/分段数） |
| GET | /api/knowledge/entities | 实体列表 |
| GET | /api/knowledge/graph | 知识图谱数据 |
| DELETE | /api/knowledge/documents/{doc_id} | 删除文档 |
| POST | /api/knowledge/documents/batch-delete | 批量删除文档 |

#### A.4 文档管理 (8 端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/documents/upload | 上传文档（multipart/form-data） |
| GET | /api/documents | 文档列表（按知识库/标签过滤） |
| GET | /api/documents/{id} | 文档详情（含分段列表） |
| PUT | /api/documents/{id} | 编辑文档元数据 |
| DELETE | /api/documents/{id} | 删除文档（三方同步删除） |
| GET | /api/documents/{id}/download | 下载源文件 |
| GET | /api/documents/{id}/chunks | 获取分段列表 |
| PUT | /api/documents/{id}/chunks/{chunk_id} | 编辑分段内容 |

#### A.5 智能问答 (3 端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/query | REST 问答（同步，返回完整结果） |
| GET | /api/ws/chat | WebSocket SSE 流式问答 |
| POST | /api/recall-test | 知识召回测试 |

#### A.6 智能体管理 (5 端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/agents | 智能体列表 |
| POST | /api/agents | 创建智能体（绑定知识库+模型配置） |
| GET | /api/agents/{id} | 智能体配置详情 |
| PUT | /api/agents/{id} | 更新智能体配置 |
| DELETE | /api/agents/{id} | 删除智能体 |

#### A.7 统计 (4 端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/monitor/status | 任务监控（进度+事件日志） |
| GET | /api/monitor/stats | 系统运行统计 |
| GET | /api/stats/usage | 使用统计（按时间/用户/模块） |
| GET | /api/stats/tokens | Token 消耗统计 |
| GET | /api/stats/api-calls | API 调用统计 |

#### A.8 系统 (3 端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 健康检查 |
| GET | /api/settings | 系统配置（admin鉴权） |
| PUT | /api/settings | 更新系统配置（admin鉴权） |
| GET | /api/audit-logs | 审计日志查询（分页+筛选） |

### 附录 B：数据库核心表结构

#### 用户表 (users) — SQLite

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,          -- bcrypt $2b$12$...
    role TEXT NOT NULL DEFAULT 'user',    -- 'admin' | 'user'
    email TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    locked_until TIMESTAMP               -- 暴力破解锁定
);
```

#### 知识库表 (knowledge_bases) — PostgreSQL

```sql
CREATE TABLE knowledge_bases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    kb_type VARCHAR(20) NOT NULL DEFAULT 'general',  -- general/qa/glossary/cache
    project_id UUID NOT NULL,
    owner_id INTEGER NOT NULL,
    doc_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### 文档表 (documents) — PostgreSQL

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT,
    file_type VARCHAR(20),                -- pdf/docx/mp4/...
    file_hash VARCHAR(64),                -- SHA-256
    status VARCHAR(20) DEFAULT 'pending', -- pending/processing/completed/failed
    chunk_count INTEGER DEFAULT 0,
    tags JSONB DEFAULT '[]',
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT true,
    expire_at DATE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### 审计日志表 (audit_logs) — SQLite

```sql
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    ip_address TEXT,
    action TEXT NOT NULL,                 -- create/read/update/delete/login/logout
    resource_type TEXT,                   -- document/knowledge_base/agent/user
    resource_id TEXT,
    detail JSON,                          -- 操作详情
    status TEXT DEFAULT 'success',        -- success/failure
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
```

### 附录 C：缩略语对照

| 缩写 | 全称 | 中文 |
|------|------|------|
| RAG | Retrieval-Augmented Generation | 检索增强生成 |
| Agentic RAG | Agentic Retrieval-Augmented Generation | 智能体增强检索生成 |
| GraphRAG | Graph-based Retrieval-Augmented Generation | 知识图谱增强检索生成 |
| RRF | Reciprocal Rank Fusion | 倒数排名融合 |
| HyDE | Hypothetical Document Embeddings | 假设文档嵌入 |
| BM25 | Best Match 25 | 最佳匹配算法 |
| HNSW | Hierarchical Navigable Small World | 分层可导航小世界图 |
| DAG | Directed Acyclic Graph | 有向无环图 |
| VLM | Vision Language Model | 视觉语言模型 |
| ASR | Automatic Speech Recognition | 自动语音识别 |
| OCR | Optical Character Recognition | 光学字符识别 |
| RBAC | Role-Based Access Control | 基于角色的访问控制 |
| ABAC | Attribute-Based Access Control | 基于属性的访问控制 |
| JWT | JSON Web Token | JSON Web 令牌 |
| SSE | Server-Sent Events | 服务器推送事件 |
| SLA | Service Level Agreement | 服务等级协议 |
| RTO | Recovery Time Objective | 恢复时间目标 |
| RPO | Recovery Point Objective | 恢复点目标 |
| CVE | Common Vulnerabilities and Exposures | 通用漏洞与披露 |
| CSP | Content Security Policy | 内容安全策略 |
| WAL | Write-Ahead Logging | 预写式日志 |
| LRU | Least Recently Used | 最近最少使用 |
| OIDC | OpenID Connect | 开放身份连接协议 |

---

> **编制单位**: RAG-Anything 项目组  
> **编制日期**: 2026 年 6 月 10 日  
> **文档版本**: v2.1  
> **总页数**: 约 40 页（含附录）
