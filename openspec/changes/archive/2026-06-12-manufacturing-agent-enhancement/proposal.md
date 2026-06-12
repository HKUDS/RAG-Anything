# Proposal: 智能制造专业智能体 — 综合增强

## Why

第一版制造智能体已完成模块骨架（31 个 Python 文件 + 3 个前端页面 + 15 个 API 端点），但存在三个核心缺口：① 知识库无真实数据，所有功能处于空转状态；② 前端缺乏专业可视化（知识图谱、代码编辑器、视频播放器）；③ QA 引擎未对接 RAG-Anything 检索引擎，回答无检索支撑。本次综合增强解决这三个缺口，使系统从"可演示原型"升级为"可实际使用的产品"。

## What Changes

- **新增** 数据导入工具集：批量导入大赛赛题 PDF/Word → 结构化入库、工艺文档批量导入、故障案例 JSON 导入、教材知识点 CSV 导入
- **新增** 知识图谱 D3 可视化：力导向图展示赛项知识结构，支持缩放/拖拽/点击展开谱系
- **新增** G 代码编辑器组件：语法高亮、行号、风险实时标注、一键解析
- **新增** 视频片段播放器：帧预览列表、时间戳跳转、关联片段推送
- **新增** QA 引擎 RAG 对接：将 `QAEngine` 的检索层接入现有 RAG-Anything 实例，实现真正的向量+BM25 混合检索
- **新增** 故障诊断对接案例库：将 `FaultDiagnosisEngine` 的案例匹配接入真实 `FaultCaseLibrary`
- **增强** 看板页面：添加导入进度指示、实时知识库规模变化展示

## Capabilities

### New Capabilities

- `data-import-tools`: 数据导入工具集。包含赛题批量导入脚本、工艺文档导入器、故障案例导入器、教材知识点 CSV 导入器。所有导入器输出结构化 JSON 并自动触发知识图谱节点创建和向量化。
- `frontend-visualization`: 前端专业可视化增强。包含 D3 力导向知识图谱、G 代码编辑器（语法高亮+风险标注）、视频片段播放器（帧预览+时间戳跳转）。复用现有 warm-theme 设计系统。
- `rag-integration`: RAG 检索引擎对接。将制造智能体的 QA 引擎、故障诊断引擎、视频定位器与服务器已有 RAG-Anything 实例和 LLM 配置对接，实现真正的检索增强生成。

### Modified Capabilities

无。本变更是对现有制造智能体模块的增强和对接，不修改已有 spec 级别的行为。

## Impact

- **新增文件**: `scripts/import_exams.py`、`scripts/import_fault_cases.py`、`scripts/import_processes.py` — 数据导入工具脚本
- **新增组件**: `frontend/src/components/KnowledgeGraphD3.jsx`、`frontend/src/components/GCodeEditor.jsx`、`frontend/src/components/VideoSegmentPlayer.jsx`
- **修改文件**: `server.py`（QA/诊断端点接入真实 RAG）、`frontend/src/pages/ManufacturingKnowledgePage.jsx`（集成图谱可视化）、`frontend/src/pages/ManufacturingAgentPage.jsx`（集成代码编辑器）、`frontend/src/pages/ManufacturingDashboardPage.jsx`（导入进度）
- **依赖**: 复用已有 `d3`（前端已有）、新增 `react-syntax-highlighter`（G 代码高亮）
- **数据**: 需准备至少 1 个赛项的赛题数据、5+ 条故障案例、3+ 份工艺文档用于验证导入流程
