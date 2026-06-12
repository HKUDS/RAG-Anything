# Design: 智能制造专业智能体 — 综合增强

## Context

第一版制造智能体已完成完整的模块架构和前后端骨架，但存在三个能力缺口：
1. 知识库空转 — 无真实数据，所有检索/问答/诊断均返回空结果
2. 前端基础 — 仅有列表和卡片展示，缺乏专业领域可视化
3. QA 引擎独立 — 未对接已有 RAG-Anything 检索引擎

本次增强聚焦于填补这三个缺口，使系统具备实际可用性。

## Goals / Non-Goals

**Goals:**
- 提供一键式数据导入工具，将赛题/工艺/案例数据批量入库
- 知识图谱页面集成 D3 力导向图可视化
- 代码解析标签页集成语法高亮编辑器
- QA 引擎对接 RAG-Anything 真实检索
- 故障诊断引擎对接 FaultCaseLibrary 真实案例

**Non-Goals:**
- 不修改 RAG-Anything 核心检索引擎
- 不引入新的数据库或存储后端
- 不构建独立的视频处理流水线（复用已有 video-frame-extraction）
- 不修改已有 API 接口契约（仅增强后端实现）

## Decisions

### Decision 1: 数据导入采用 CLI 脚本而非 Web UI

**选择**: Python CLI 脚本（`scripts/import_*.py`），通过已有 manufacturing 模块 API 入库。

**备选方案**: Web 上传界面 — 交互更好但开发量大，且批量导入场景下 CLI 更实用。

**理由**: 大赛赛题通常为批量文件（50+ PDF），CLI 脚本支持断点续传和错误恢复，比 Web 上传更稳定。后续可基于脚本封装 Web UI。

### Decision 2: D3 力导向图直接操作 SVG，不引入 ECharts/vis.js

**选择**: 使用项目已有的 d3 v7，直接在 SVG 上绘制力导向图。

**理由**: d3 已是前端依赖，无需新增包。力导向图适合展示知识图谱的节点-关系结构，D3 的 force simulation 对此有原生支持。

### Decision 3: G 代码编辑器使用 textarea + 自定义高亮层

**选择**: 基于 textarea + overlay div 实现语法高亮，不引入 CodeMirror/Monaco。

**理由**: G 代码语法简单（G/M 指令 + 坐标），不需要完整的代码编辑器框架。轻量实现减少约 200KB 打包体积。

### Decision 4: RAG 对接采用依赖注入模式

**选择**: 在 server.py 的 `_get_mfg_agent_components()` 中，将已有的 `RAGAnything` 实例和 LLM 函数注入制造模块的 QAEngine/VideoLocator/FaultDiagnosisEngine。

**理由**: 不修改制造模块内部代码，仅通过 server.py 的初始化逻辑完成对接。保持模块的独立性和可测试性。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| 数据导入脚本因文件格式不一致失败 | 每类文件支持多种解析策略，失败文件跳过并记录日志 |
| D3 力导向图在大节点量（>500）时性能下降 | 限制首次渲染 200 节点，支持按赛项筛选 |
| RAG 检索延迟影响 QA 响应时间 | 设置 3s 超时降级，超时后返回无检索结果 |
| G 代码编辑器正则高亮在高并发下卡顿 | 对 >1000 行代码使用 Web Worker 异步高亮（后续优化） |

## Open Questions

- [ ] 赛题数据来源和格式是否已确定？（PDF 扫描件 vs 电子文档）
- [ ] 是否有现成的故障案例 JSON 数据集？还是需要从零构建？
- [ ] D3 图谱交互需求：是否需要支持节点编辑/拖拽重排/导出图片？
