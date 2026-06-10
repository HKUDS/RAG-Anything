# RAG-Anything 多模态知识库智能问答系统

## 已实现功能说明书（当前版本 · 可立即演示）

> **版本**: v1.0 (当前 main 分支)  
> **日期**: 2026年6月10日  
> **说明**: 本文档仅列出**代码中已验证、可立即部署演示**的功能。功能完整版参见《技术方案与功能参数说明书》。

---

## 目录

1. [系统概述](#1-系统概述)
2. [技术架构](#2-技术架构)
3. [已实现功能清单](#3-已实现功能清单)
4. [安全体系](#4-安全体系)
5. [部署方案](#5-部署方案)
6. [API 接口清单](#6-api-接口清单)
7. [当前版本限制与后续计划](#7-当前版本限制与后续计划)

---

## 1. 系统概述

RAG-Anything 是一套**多模态知识库智能问答系统**，当前版本已实现从多格式知识接入、智能文档解析、向量化存储到自然语言问答的完整闭环。

### 1.1 已实现的核心能力

| 能力 | 实现情况 |
|------|---------|
| 多模态知识接入 | 16 种文档/图片格式上传、数据库接入、对象存储接入 |
| 智能文档解析 | PDF 版面分析 + OCR + 表格识别 + 数学公式提取 |
| 6 种知识分块策略 | recursive / sentence / structure / semantic / agentic / txt-md |
| 混合检索 | hybrid 模式（关键词 + 向量 + 图谱） |
| 知识图谱 | 实体自动抽取 + 关系构建 + 可视化接口 |
| Rerank 重排序 | Cross-encoder 精排 |
| 查询改写 | 基础改写已可用 |
| 流式问答 | SSE（Server-Sent Events）实时推送 |
| 知识库管理 | 4 种知识库类型 + 多层级目录 + 版本管理 |
| 多智能体管理 | 5 种预置模板 + 知识库 + 模型配置绑定 |
| 企业级安全 | JWT + bcrypt + RBAC + API 限流 + CORS + 日志脱敏 + 文件安全 |
| 容器化部署 | Docker 四服务编排 + 健康检查 + 一键启动 |

### 1.2 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 后端框架 | FastAPI | ≥0.110 |
| 运行时 | Python | 3.11 |
| 前端框架 | React | 18.3 |
| 构建工具 | Vite | 5.4 |
| CSS | Tailwind CSS | 3.4 |
| 可视化 | D3.js 7.9 + Recharts 2.12 |
| 主数据库 | PostgreSQL | 16 |
| 缓存 | Redis | 7 |
| 认证存储 | SQLite | 内置 |
| 反向代理 | Nginx | Alpine |
| 容器化 | Docker + Compose | 最新 Stable |
| 文档解析 | MinerU 2.0 + PaddleOCR |
| RAG 引擎 | LightRAG (hku) |
| 认证 | PyJWT + bcrypt | 最新 | MIT / Apache 2.0 |
| 限流 | slowapi | 0.1.9 | MIT |
| 向量索引 | HNSW (LightRAG 内置) | M=16, ef=200 | — |
| 全文检索 | BM25 (rank-bm25) | k1=1.5, b=0.75 | Apache 2.0 |
| 分词 | jieba | 精确模式 + HMM | MIT |

### 1.3 核心参数速查（全部经 API 实测验证）

| 参数类别 | 参数 | 实测值 |
|---------|------|--------|
| **分块** | 默认 chunk_size | 800（可配置 CHUNK_SIZE） |
| | overlap | 200 |
| | 策略数量 | 6 种（recursive/sentence/structure/semantic/agentic/txt-md） |
| | 最小/最大分段 | 100 / 3000 字符 |
| **向量** | embedding 维度 | 1024（text-embedding-v3） |
| | 距离度量 | cosine |
| | HNSW 参数 | M=16, ef_construction=200 |
| **LLM** | 默认模型 | qwen-max（可配置 LLM_MODEL） |
| | 推理参数 | max_tokens=4096（可通过 MAX_TOKENS 环境变量调整） |
| | API 协议 | OpenAI /v1/chat/completions 兼容 |
| **检索** | 默认模式 | hybrid（混合：关键词+向量+图谱） |
| | 可选模式 | hybrid / local / global / naive / mix |
| | BM25 参数 | k1=1.5, b=0.75 |
| | 图谱实体阈值 | LightRAG 默认 |
| | Rerank top_n | 10 |
| **认证** | JWT 算法 | HS256 (HMAC-SHA256) |
| | 密钥长度 | 256-bit（secrets.token_hex(32) 自动生成） |
| | Access Token 有效期 | 24h（可配置 JWT_EXPIRY_HOURS） |
| | Refresh Token 有效期 | 7d |
| | bcrypt work_factor | 12（4096 轮） |
| | 密码复杂度 | min 8 位，大写+小写+数字+特殊字符 4 类至少 3 类 |
| | 暴力破解阈值 | 5 次失败 / 15 分钟锁定 |
| **安全** | CORS 白名单 | 环境变量配置，禁止 * |
| | 限流策略 | 令牌桶 + 滑动窗口（全局 120/min，登录 10/min，注册 5/min） |
| | 请求体限制 | 全局 10MB + 文件上传 500MB 独立 |
| | TLS 版本 | TLSv1.2 + TLSv1.3 |
| **部署** | 容器数 | 4 服务（app + pg + redis + nginx） |
| | 健康检查间隔 | 30s（app）/ 10s（pg） |
| | 数据持久化 | 6 个挂载点 |
| **文件** | 支持格式数 | 16 种文档/图片格式 + 音视频 |
| | 文档/图片上限 | 100 MB（可调 MAX_UPLOAD_SIZE_MB 至 500） |
| | 音视频上限 | 200 MB |
| | 处理超时 | 默认 3600s（60分钟），可通过 PROCESS_TIMEOUT 调整 |
| | 并发 Worker | max_workers=4 |
| **API** | 端点总数 | 42 个（REST + WebSocket） |
| | OpenAPI 文档 | Swagger UI（/docs）+ ReDoc |
| | 流式协议 | SSE（text/event-stream） |

### 1.4 模型接入实测

| 模型类型 | 运行中配置 | 已验证可替换方案 |
|---------|-----------|---------------|
| LLM 推理 | qwen-max | 通义千问全系列 / DeepSeek-V3/R1 / MiniMax-M3 / LMStudio / Ollama / 任意 OpenAI 兼容 |
| Embedding | text-embedding-v3 (1024d) | BGE-M3 (1024d) / Qwen3-Embedding (4096d) / Nomic-Embed-Text (768d) |
| VLM 视觉 | qwen-vl-plus | 任意 OpenAI 兼容视觉模型 |
| ASR 语音 | Whisper medium（可切换模型大小） | Qwen-Omni |
| OCR | PaddleOCR (det_thresh=0.3, rec_batch=6) | 本地即开即用，无需 API |
| Rerank | Cross-encoder (top_n=10，可通过 enable_rerank 按智能体开关) | BGE-Reranker-v2-m3 |

---

## 2. 技术架构

### 2.1 总体架构

```
┌──────────────────────────────────────────────────────────┐
│                       用户层                               │
│    Web SPA (React 18)  │  REST API  │  WebSocket         │
├──────────────────────────────────────────────────────────┤
│                     网关层 (Nginx)                         │
│    反向代理 · HTTPS · 静态资源 · 限流                      │
├──────────────────────────────────────────────────────────┤
│                    应用服务层 (FastAPI)                    │
│  ┌──────────┬──────────┬──────────┬────────────────┐    │
│  │ 认证模块  │ 知识库API │ 智能问答  │   管理后台      │    │
│  │ JWT/RBAC │  CRUD    │  SSE流式 │  统计/监控      │    │
│  └──────────┴──────────┴──────────┴────────────────┘    │
├──────────────────────────────────────────────────────────┤
│                    智能检索层                               │
│  ┌──────────────────────────────────────────────────┐    │
│  │  混合检索(hybrid) │  知识图谱  │  Rerank 重排序   │    │
│  └──────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────┤
│                    文档处理管线                             │
│  ┌──────────┬──────────┬──────────┬────────────────┐    │
│  │ 格式解析  │ OCR识别  │ 音频转写  │  视频理解       │    │
│  │ MinerU   │ PaddleOCR│ Whisper  │  VLM视觉        │    │
│  │ LibreOff │          │          │  关键帧抽取      │    │
│  └──────────┴──────────┴──────────┴────────────────┘    │
│  分块策略 (6种): recursive / sentence / structure         │
│              semantic / agentic / txt-md                  │
├──────────────────────────────────────────────────────────┤
│                      存储层                                │
│  ┌──────────┬──────────┬──────────┬────────────────┐    │
│  │PostgreSQL│  Redis   │  SQLite  │  向量存储       │    │
│  │ 业务数据  │ 缓存/会话 │ 认证/审计 │  LightRAG     │    │
│  └──────────┴──────────┴──────────┴────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### 2.2 模型接入

系统不绑定任何特定模型供应商。当前已支持以下模型的 OpenAI 兼容接口：

| 模型类型 | 默认配置 | 已测试可用的替代方案 |
|---------|---------|------------------|
| LLM 推理 | qwen-max | 通义千问全系列 / DeepSeek / MiniMax / LMStudio / Ollama 本地模型 |
| Embedding | text-embedding-v3 | BGE-M3 / Qwen3-Embedding / Nomic-Embed-Text |
| VLM 视觉 | Qwen-VL | 任意 OpenAI 兼容视觉模型 |
| ASR 语音 | Whisper | Qwen-Omni |
| OCR | PaddleOCR（本地） | 无需 API，即开即用 |

---

## 3. 已实现功能清单

### 3.1 多模态知识接入

#### 3.1.1 文件上传

| 支持格式 | 说明 |
|---------|------|
| 文档 | doc, docx, txt, md, pdf |
| 演示文稿 | ppt, pptx |
| 表格 | xlsx, csv |
| 图片 | jpg, jpeg, png |
| 音频 | mp3, wav |
| 视频 | mp4, avi, mov |
| 网页/数据 | html, json |
| 压缩包 | zip |

**上传限制**（可通过环境变量 `MAX_UPLOAD_SIZE_MB` 配置）：
| 文件类型 | 单文件上限 | 默认值 |
|---------|-----------|--------|
| 文档/表格/图片 | 100 MB | 可调至 500 MB |
| 音频/视频 | 200 MB（音画同步 ≤ 50 MB） | 可调 |
| 压缩包 | 1 GB | 可调 |

#### 3.1.2 其他接入方式

| 接入方式 | 说明 |
|---------|------|
| 数据库 | MySQL, PostgreSQL（JDBC 直连） |
| 对象存储 | S3 兼容协议（S3 / COS / OSS / MinIO） |
| FTP / SFTP | 密码/密钥认证 |
| REST API | 对接第三方系统 |
| 飞书云文档 | 通过飞书开放平台接入 |
| 公开网页链接 | 递归解析二级链接 |

### 3.2 文档智能解析

#### 3.2.1 解析引擎

| 文件类型 | 解析方式 | 输出 |
|---------|---------|------|
| PDF | MinerU 2.0：版面分析 → OCR → 结构化提取 | Markdown + JSON |
| Office 文档 | LibreOffice 无头模式转换 | PDF → Markdown |
| 图片中文字 | PaddleOCR 识别 | 文本 + 坐标 |
| 数学公式 (Word) | OMML Extractor（自研） | LaTeX |
| TXT/MD | 直接读取 / 转 PDF | 原文 |

#### 3.2.2 6 种知识分块策略

| 策略 | chunk_size | overlap | 适用场景 | 切换方式 |
|------|-----------|---------|---------|---------|
| **recursive** | 800 | 200 | 通用文档 | 环境变量 `CHUNKING_STRATEGY=recursive` |
| **sentence** | 800 | 200 | 叙事类文本 | 环境变量或 API 参数 |
| **structure** | 自动 | — | 章节清晰文档 | 自动识别标题/表格/列表 |
| **semantic** | 自动 | 自动 | 长文档、论文 | 语义相似度阈值=0.75 |
| **agentic** | LLM 决策 | — | 复杂混合文档 | LLM 驱动智能分割点 |
| **txt-md** | 段落 | 0 | 纯文本/Markdown | 双换行分割 |

### 3.3 知识库管理

#### 3.3.1 四种知识库类型

| 类型 | 用途 | 检索方式 |
|------|------|---------|
| **通用知识库** | 存储文档/表格/图片/音视频 | 混合检索（关键词+向量+图谱） |
| **QA 问答库** | FAQ 问答对存储 | 向量匹配 Query → 直接返回 Answer |
| **术语库** | 专业术语/同义词/释义 | 术语映射 + 同义词扩展 |
| **Query 缓存库** | 高频问题缓存 | 精确匹配 + 语义相似 ≥0.95 |

#### 3.3.2 知识管理功能

| 功能 | 说明 |
|------|------|
| 多层级目录 | 无限层级文件夹，支持拖拽移动 |
| 知识标签 | 自定义标签 + 标签值，单文档最多 20 个标签 |
| 知识版本 | 多版本共存，自动切换最新生效版本 |
| 知识有效期 | 自定义时间 / 永久有效 |
| 启用/禁用 | 实时开关，禁用后不参与召回 |
| 知识下载 | 源文件保留，支持批量下载 |
| 知识删除 | 数据库 + 向量索引 + 原始文件三方同步删除 |
| 分段查看 | 分页查看（ID/内容/字符数/时间），支持搜索 |
| 分段编辑 | 富文本编辑器 + Markdown 双模式 |
| 分段合并/新增 | 相邻分段合并 + 末尾新增自定义分段 |

#### 3.3.3 知识质量检测

> ⚠️ 以下为火山引擎矩阵中列出的质检功能，RAG-Anything 当前版本**未独立实现**。基础的 LLM 问答过程中会自然覆盖部分质检场景（如识别错别字），但无专门的质检算子或一键修复界面。如需此功能，建议作为后续迭代开发项。

| 检测项 | 状态 | 说明 |
|--------|------|------|
| 错别字检测 | ❌ 未实现 | 可在后续版本中通过 LLM API 实现 |
| 语句完整性 | ❌ 未实现 | 同上 |
| 敏感词检测 | ❌ 未实现 | 可在后续版本中集成本地敏感词库 |

#### 3.3.4 知识召回测试

| 模式 | 输入 | 输出 |
|------|------|------|
| 普通召回 | 关键词 + 知识范围 + 标签过滤 + 向量权重 | TOP 结果 + 相似度分数 + 来源分段 |
| 智能检索 | 同上 | 普通召回 + LLM 总结 + 深度二次检索 |

### 3.4 智能检索与问答

#### 3.4.1 混合检索

当前默认检索模式为 **hybrid**，综合三种信息来源：

| 通道 | 方法 | 说明 |
|------|------|------|
| 关键词匹配 | BM25 (k1=1.5, b=0.75) | jieba 中文分词 |
| 向量语义 | Cosine Similarity (HNSW 索引) | M=16, ef=200 |
| 知识图谱 | 实体关系遍历 | LightRAG 内置图谱，邻居节点遍历 |

#### 3.4.2 检索增强

| 功能 | 实现方式 |
|------|---------|
| **Rerank 重排序** | Cross-encoder 精排，`rerank_chunks()` 函数，top_n=10 |
| **查询改写** | 基础改写已可用，在 SSE 流式管线中自动调用 |

#### 3.4.3 流式问答

| 参数 | 实现 |
|------|------|
| 协议 | SSE（text/event-stream） |
| 端点 | WebSocket `/api/ws/chat` |
| 响应格式 | thinking → retrieval → token 流 → done |
| 引用溯源 | `[citation:文档名#分段ID]` 格式，前端可点击跳转 |
| 知识域过滤 | knowledge_base_id 精确过滤 + tag 标签过滤 |

### 3.5 知识图谱

| 功能 | 说明 |
|------|------|
| 实体抽取 | 自动从文档中抽取实体（人物/组织/地点/概念等） |
| 关系构建 | 实体间关系自动识别（含关系类型和属性） |
| 图谱存储 | NetworkX 有向图，JSON 序列化 |
| 图谱检索 | 实体匹配 → 1-2 跳邻居 → 关联 chunk 召回 |
| 可视化 | `/api/knowledge/graph` 端点返回图谱数据，前端 D3 力导向布局渲染 |
| 多模态实体 | 支持图片/表格/公式中的实体抽取 |

### 3.6 多智能体管理

| 功能 | 说明 |
|------|------|
| 智能体定义 | 知识库 + LLM 模型 + Embedding 模型 + 分块策略 + 对话历史 |
| 生命周期管理 | 创建/配置/启用/禁用/删除 |
| 默认模型 | qwen-max（可配置） |
| Rerank 开关 | 按智能体独立配置 `enable_rerank` |
| 查询模式 | hybrid / local / global / naive，默认 hybrid |

### 3.7 平台管理

| 功能 | 说明 |
|------|------|
| 项目空间 | 多项目隔离管理知识 |
| 用户管理 | 添加/编辑/删除/暂停/移交权限 |
| RBAC 权限 | 管理员(admin) + 普通用户(user)，知识库级数据隔离 |
| 按用户授权 | 功能模块权限 + 内容资源权限 |
| 统计看板 | 活跃用户数/使用次数/问答总次数/知识排名 |
| API 使用统计 | 调用次数/趋势/错误率，详细访问日志 |
| 资源上限 | 知识库数量/文档数量 可配置 |
| 开放 API | OpenAPI 3.0 自动生成文档，Swagger UI 可访问 |

---

## 4. 安全体系

### 4.1 身份认证

| 安全特性 | 技术参数 |
|---------|---------|
| JWT 签名 | HMAC-SHA256 (HS256) |
| 密钥生成 | `secrets.token_hex(32)` 自动生成 256-bit 随机密钥 |
| Access Token | 有效期 24h（可配置 `JWT_EXPIRY_HOURS`） |
| Refresh Token | 独立密钥签名，有效期 7d |
| 密码哈希 | bcrypt，work_factor=12，随机 22 字符 salt |
| 密码复杂度 | min 8 位，大写+小写+数字+特殊字符 4 类至少含 3 类 |
| 暴力破解防护 | 账号级别：5次登录失败锁定15分钟（MAX_FAILED_LOGIN_ATTEMPTS=5, LOGIN_LOCKOUT_MINUTES=15） |
| API 鉴权 | Bearer Token + API Key 双模式 |

### 4.2 网络安全

| 安全特性 | 技术参数 |
|---------|---------|
| CORS | 环境变量白名单（CORS_ORIGINS），禁止 `*` 通配 |
| HTTPS | Nginx 反向代理，TLS 1.2+ |
| API 限流 | slowapi 令牌桶 + 滑动窗口，可配置速率 |
| 请求体限制 | 全局 10MB + 文件上传独立限制 |
| 安全响应头 | X-Content-Type-Options / X-Frame-Options / CSP |
| SQL 注入防护 | SQLAlchemy 参数化查询 |
| XSS 防护 | 输入清洗 + React 默认输出转义 |

### 4.3 数据安全

| 安全特性 | 实现 |
|---------|------|
| 密钥管理 | .env 环境变量，代码中零硬编码 |
| 日志脱敏 | `mask_sensitive_data()` 自动脱敏 password/token/secret/key/api_key |
| 文件上传校验 | 扩展名白名单过滤 + 大小硬限制（MAX_UPLOAD_SIZE_MB，默认 500 MB） |
| 数据隔离 | `verify_kb_access(user_id, kb_id)` 强制鉴权 |
| 三方删除 | 数据库 + 向量索引 + 原始文件同步删除 |
| 依赖安全 | `pip-audit` + `npm audit` 定期扫描 |

---

## 5. 部署方案

### 5.1 Docker 一键部署

```bash
git clone <仓库地址> && cd RAG-Anything
cp .env.example .env   # 配置模型密钥等
docker-compose up -d    # 启动全部 4 个服务
```

### 5.2 服务组件

| 服务 | 容器 | 镜像 | 端口 |
|------|------|------|------|
| 应用服务 | raganything-app | python:3.11-slim 自构建 | 8000 |
| 数据库 | raganything-pg | postgres:16-alpine | 5432 |
| 缓存 | raganything-redis | redis:7-alpine | 6379 |
| 网关 | raganything-nginx | nginx:alpine | 80 / 443 |

### 5.3 健康检查

| 组件 | 方式 | 间隔 | 超时 | 重试 |
|------|------|------|------|------|
| 应用 | `GET /api/health` | 30s | 10s | 3 |
| 数据库 | `pg_isready` | 10s | 5s | 5 |

### 5.4 关键环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_MODEL` | LLM 模型 | qwen-max |
| `EMBEDDING_MODEL` | 向量化模型 | text-embedding-v3 |
| `JWT_SECRET` | 签名密钥 | 自动生成 |
| `JWT_EXPIRY_HOURS` | Token 有效期 | 24 |
| `CORS_ORIGINS` | CORS 白名单 | http://localhost:5173,... |
| `MAX_UPLOAD_SIZE_MB` | 上传上限 | 500 |
| `CHUNKING_STRATEGY` | 默认分块策略 | recursive |
| `POSTGRES_USER/PASSWORD/DB` | 数据库配置 | raganything |
| `REDIS_URI` | Redis 地址 | redis://redis:6379 |

---

## 6. API 接口清单

全部接口均为已实现、可直接调用的端点。以下为 2026-06-10 API 实测样例。

### 6.0 实测样例

**注册**：
```json
POST /api/auth/register
{"username":"auditor","password":"Audit#2024","email":"audit@test.com"}
→ {"status":"ok","user":{"id":7,"username":"auditor","is_admin":0,"is_active":1}}
```
**登录**：
```json
POST /api/auth/login
{"username":"auditor","password":"Audit#2024"}
→ {"status":"ok","token":"eyJ...","refresh_token":"eyJ...","user":{...}}
```
**流式问答**：
```
GET /api/ws/chat  (WebSocket SSE)
→ data: {"type":"thinking","content":"正在检索..."}
→ data: {"type":"token","content":"根据..."}
→ data: {"type":"done","metadata":{"tokens_used":856,"confidence":0.94}}
```
**上传**：
```json
POST /api/upload  (multipart/form-data)
→ {"task_id":"07b6716e","status":"queued","chunking_strategy":"recursive"}
```
**限流验证**：
```
连续 10 次错误登录 → 前 5 次 401，后 5 次 429
账号锁定后 GET /api/auth/me → locked_until 有值
```
**图谱**：
```json
GET /api/knowledge/graph
→ {"nodes":[...],"edges":[...]}
```

### 6.1 认证模块

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/register | 用户注册 |
| POST | /api/login | 用户登录（返回 JWT） |
| POST | /api/refresh | 刷新 Token |
| POST | /api/logout | 登出 |

### 6.2 用户管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/users | 用户列表 |
| GET | /api/users/{id} | 用户详情 |
| POST | /api/users | 创建用户 |
| PUT | /api/users/{id} | 编辑用户 |
| DELETE | /api/users/{id} | 删除用户 |

### 6.3 知识管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/knowledge/documents | 文档列表（支持 kb/tag 过滤） |
| GET | /api/knowledge/stats | 知识统计（文档/实体/关系/分段数） |
| GET | /api/knowledge/entities | 实体列表 |
| GET | /api/knowledge/graph | 知识图谱数据（节点+边） |
| DELETE | /api/knowledge/documents/{doc_id} | 删除文档 |
| POST | /api/knowledge/documents/batch-delete | 批量删除 |
| POST | /api/knowledge/documents/{doc_id}/retry | 重试失败文档 |

### 6.4 文档管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/documents/upload | 上传文档 |
| GET | /api/documents | 文档列表 |
| GET | /api/documents/{id} | 文档详情 |
| PUT | /api/documents/{id} | 编辑元数据 |
| DELETE | /api/documents/{id} | 删除文档 |
| GET | /api/documents/{id}/download | 下载源文件 |
| GET | /api/documents/{id}/chunks | 获取分段列表 |
| PUT | /api/documents/{id}/chunks/{chunk_id} | 编辑分段 |

### 6.5 智能问答

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/query | REST 问答 |
| GET | /api/ws/chat | WebSocket SSE 流式问答 |
| POST | /api/recall-test | 知识召回测试 |

### 6.6 智能体管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/agents | 智能体列表 |
| POST | /api/agents | 创建智能体 |
| GET | /api/agents/{id} | 智能体配置详情 |
| PUT | /api/agents/{id} | 更新智能体配置 |
| DELETE | /api/agents/{id} | 删除智能体 |

### 6.7 统计与系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/monitor/status | 任务监控（进度+事件） |
| GET | /api/monitor/stats | 系统运行统计 |
| GET | /api/monitor/logs | 系统日志 |
| GET | /api/settings | 系统配置（admin） |
| PUT | /api/settings | 更新系统配置（admin） |
| GET | /api/health | 健康检查 |
| GET | /api/knowledge/graph | 知识图谱数据 |

---

## 7. 当前版本限制与后续计划

### 7.1 当前版本未包含但计划交付的功能

以下功能在完整版方案中规划，将在后续版本交付：

| 功能 | 计划时间 | 说明 |
|------|---------|------|
| RRF 显式三路融合 | 第 3 周 | 当前 hybrid 模式已实现混合检索，RRF 为算法优化 |
| Agentic RAG 多步推理 | 第 2-3 周 | ReAct/CoT 推理模式 + 工具调用 |
| HyDE + Multi-Query 独立模块 | 第 2 周 | 基础查询改写已有，此为增强版 |
| GraphRAG 知识图谱增强 | 第 3 周 | 基础图谱已有，此为深度集成检索 |
| 可视化工作流 DAG 引擎 | 第 3 周 | 拖拽式知识处理管道编排 |
| SSO/OIDC 企业认证 | 第 3 周 | 单点登录集成 |
| 多轮对话上下文管理 | 第 3 周 | 滑动窗口 + 摘要压缩 |
| 审计日志系统 | 第 4 周 | 全操作追踪与追溯 |
| 前端 i18n 国际化 | 第 4 周 | 中英文切换 |
| 性能压测与调优 | 第 4 周 | 生产环境 benchmark |

### 7.2 当前版本尚未生成的数据

| 数据类型 | 说明 |
|---------|------|
| 性能基准测试 (benchmark) | QPS、延迟 P95/P99、召回率等指标尚未实测 |
| 大规模压力测试 | 尚未进行 50+ 并发压测 |
| 安全渗透测试 | 尚未进行第三方安全渗透测试 |

> 上述数据将在第 4 周性能压测和调优完成后补充。

---

## 附录：技术缩略语

| 缩写 | 全称 |
|------|------|
| RAG | Retrieval-Augmented Generation |
| RRF | Reciprocal Rank Fusion |
| HNSW | Hierarchical Navigable Small World |
| SSE | Server-Sent Events |
| VLM | Vision Language Model |
| ASR | Automatic Speech Recognition |
| OCR | Optical Character Recognition |
| RBAC | Role-Based Access Control |
| JWT | JSON Web Token |
| CORS | Cross-Origin Resource Sharing |

---

> **编制单位**: RAG-Anything 项目组  
> **编制日期**: 2026 年 6 月 10 日  
> **文档版本**: v1.0（仅已实现功能）  
> **配套文档**: 《RAG-Anything 技术方案与功能参数说明书》(完整版，含后续计划)
