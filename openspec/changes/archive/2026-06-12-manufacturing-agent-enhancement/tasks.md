# Tasks: 智能制造专业智能体 — 综合增强

## 1. 数据导入工具集

- [x] 1.1 创建 `scripts/import_exams.py` — 赛题批量导入脚本：遍历目录解析 PDF/Word → 调用 ExamStructurer 入库 → 创建知识图谱节点 → 输出导入报告
- [x] 1.2 创建 `scripts/import_fault_cases.py` — 故障案例批量导入脚本：解析 JSON 数组 → 校验必填字段 → 调用 FaultCaseLibrary.add_case() 入库 → 输出统计
- [x] 1.3 创建 `scripts/import_processes.py` — 工艺文档导入脚本：遍历目录 → 调用 ProcessLibrary.ingest_document() 自动分类入库
- [x] 1.4 创建 `scripts/import_textbook_kps.py` — 教材知识点 CSV 导入脚本：解析 CSV → 调用 TextbookAligner.align() 自动对齐赛项能力
- [x] 1.5 创建示例数据目录 `data/manufacturing_kb/` 及 README，说明数据格式和导入流程

## 2. RAG 检索引擎对接

- [x] 2.1 改造 `server.py` 的 `_get_mfg_agent_components()`：将已有 RAGAnything 实例注入 QAEngine.rag_client，实现真正的混合检索
- [x] 2.2 改造 QAEngine 检索超时处理：添加 3s 超时 + 降级为无检索模式
- [x] 2.3 改造 FaultDiagnosisEngine 对接：确保 `_get_mfg_agent_components()` 中的 FaultCaseLibrary 实例正确传入诊断引擎，案例匹配走真实检索
- [x] 2.4 添加 LLM 配置缺失检测：`_get_mfg_agent_components()` 中检查 API_KEY 等环境变量，缺失时打印明确警告并返回降级错误

## 3. 前端可视化增强

- [x] 3.1 创建 `frontend/src/components/KnowledgeGraphD3.jsx` — D3 力导向图组件：节点按类型着色、边按关系类型显示、支持缩放拖拽、点击节点展示谱系侧边栏
- [x] 3.2 创建 `frontend/src/components/GCodeEditor.jsx` — G 代码编辑器组件：行号、语法高亮（G=蓝/M=绿/坐标=橙/注释=灰）、风险行标注、一键解析按钮
- [x] 3.3 创建 `frontend/src/components/VideoSegmentPlayer.jsx` — 视频片段播放器：片段缩略图列表、起止时间戳、点击跳转播放
- [x] 3.4 改造 `ManufacturingKnowledgePage.jsx`：知识图谱标签集成 D3 组件替代节点列表
- [x] 3.5 改造 `ManufacturingAgentPage.jsx`：代码解析标签集成 GCodeEditor 组件
- [x] 3.6 改造 `ManufacturingDashboardPage.jsx`：添加自动刷新（5s 轮询）、数据导入进度指示

## 4. 集成验证

- [x] 4.1 端到端测试：创建 3 条示例故障案例 JSON → 导入 → 通过 API 验证检索 → 通过前端验证展示
- [x] 4.2 端到端测试：创建 3 个示例知识图谱节点 → 验证图谱 API → D3 可视化展示
- [x] 4.3 端到端测试：QA 检索管道验证 — RAG 实例注入正确，超时降级机制就绪
- [x] 4.4 前端构建验证：`npm run build` 成功，零报错，新增组件正确打包
