# 智能制造专业智能体 — 架构设计文档

> **版本**: v1.0 | **状态**: 初稿 | **最后更新**: 2026-06-12

## 1. 系统上下文 (C4 Level 1)

```
┌─────────────────────────────────────────────────────────┐
│                    天工讲堂平台                           │
│  ┌──────────────────────────────────────────────────┐  │
│  │           智能制造专业智能体                        │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │  │
│  │  │ 知识图谱  │  │ 知识库   │  │  智能体核心   │  │  │
│  │  │ 模块     │  │ 流水线   │  │  (QA/诊断)   │  │  │
│  │  └──────────┘  └──────────┘  └──────────────┘  │  │
│  └──────────────────────────────────────────────────┘  │
│                         │                               │
│              RAG-Anything 核心引擎                       │
│         (解析/检索/图谱/多模态处理)                      │
└─────────────────────────────────────────────────────────┘
```

## 2. 容器图 (C4 Level 2)

| 容器 | 技术 | 职责 |
|------|------|------|
| Manufacturing Agent API | Python/FastAPI | RESTful API 接口层 |
| Knowledge Graph Service | Python/LightRAG | 知识图谱 CRUD + 谱系查询 |
| Knowledge Pipeline | Python | 多模态数据处理流水线 |
| Agent Core | Python/LLM | 问答、诊断、代码解析 |
| Config & Admin | YAML + Web UI | 配置管理与运维面板 |

## 3. 目录结构

```
raganything/manufacturing/
├── __init__.py
├── knowledge_graph/
│   ├── __init__.py
│   ├── models.py       # 数据模型
│   ├── parser.py       # 赛题解析器
│   ├── tagger.py       # 自动打标服务
│   └── graph_api.py    # 图谱 API
├── knowledge_pipeline/
│   ├── __init__.py
│   ├── exam_structurer.py
│   ├── scoring_digitizer.py
│   ├── process_library.py
│   ├── fault_case_library.py
│   ├── textbook_aligner.py
│   ├── resource_annotator.py
│   ├── data_cleaner.py
│   └── copyright_reviewer.py
├── agent/
│   ├── __init__.py
│   ├── qa_engine.py
│   ├── video_locator.py
│   ├── source_tracer.py
│   ├── lineage_pusher.py
│   ├── code_parser.py
│   ├── fault_diagnosis.py
│   ├── deployment_config.py
│   └── api.py
└── deployment/
    ├── __init__.py
    ├── test_harness.py
    ├── school_deployer.py
    ├── enterprise_adapter.py
    ├── tiangong_platform.py
    ├── ops_monitor.py
    └── dashboard.py
```

## 4. 关键决策记录 (ADR)

| ADR | 决策 | 理由 |
|-----|------|------|
| ADR-001 | 分层架构（知识层→智能体层→应用层） | 独立迭代，复用核心 |
| ADR-002 | 复用 LightRAG 图存储 | 避免引入额外图数据库 |
| ADR-003 | 视频时间戳索引 + 向量检索 | 复用已有视频帧提取能力 |
| ADR-004 | LLM + 工具调用架构 | 精确操作交给专用工具 |
