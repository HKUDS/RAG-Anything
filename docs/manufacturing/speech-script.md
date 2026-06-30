# RAG-Anything 智能制造智能体技术演讲

---

## 开场

各位老师好，我来介绍 RAG-Anything 在智能制造专业的技术方案。

---

## 一、系统架构

采用 C4 模型，分四层：

**系统层**: RAG-Anything 引擎 + 智能制造领域模块 + 天工讲堂平台

**容器层**:
- 知识图谱服务：节点/边管理、关系查询、谱系树
- 多模态知识管道：文档解析、赛题结构化、教材对齐
- 智能体服务：文本问答、故障诊断、视频定位、代码解析
- 部署运维：院校部署、监控、看板

**组件层**:
- knowledge_graph: models.py, parser.py, tagger.py, graph_api.py
- knowledge_pipeline: process_library, fault_case_library, exam_structurer, textbook_aligner
- agent: qa_engine, fault_diagnosis, video_locator

---

## 二、核心参数

### 引擎配置

- parse_method: auto，parser: mineru
- 多模态开关：image/table/equation 开启，video 默认关闭
- max_concurrent_files: 1

### LightRAG 参数

- top_k: 10，cosine_threshold: 可配置
- max_parallel_insert: 可配置
- chunk_token_size: 可配置

### 问答引擎

- top_k: 10，citation_required: True
- query_mode: rrf，max_steps: 3

### 故障诊断

- max_dialog_rounds: 5
- confidence_threshold: 0.6

### 视频定位

- frame_window: 3
- min_segment_duration: 5.0 秒

---

## 三、实现方法

### 两级问答策略

**Tier 1 - 直接检索**:
1. RRF 融合检索
2. 上下文 ≥ 200 字符 → 直接 LLM
3. 上下文 < 50 字符 → 进入 Tier 2

**Tier 2 - AgenticRAG**:
1. ReAct 循环：思考 → 检索 → 推理
2. 最大步数 3
3. 自主调用 SearchTool

### 三级图片匹配

1. **图号精确匹配**: 提取"图N"，映射到图片序列
2. **Caption 关键字**: jieba 分词，交集匹配
3. **路径关键字**: 文件名/目录名匹配

### 故障诊断流程

1. 用户描述故障
2. 案例库向量匹配 (cosine)
3. 选择追问模板：加工精度/表面质量/机械振动/电气故障
4. 多轮对话缩小范围
5. 置信度计算：avg_score × 0.7 + concentration × 0.3
6. 置信度 ≥ 0.8 或轮数 ≥ 5 → 输出结论

### 知识图谱

**节点类型**: competition_topic, skill_point, knowledge_point, tool, standard

**关系类型**: requires(前置), advances_to(进阶), related_to(关联), evaluates(评分), applies_in(场景)

### 教材对齐

- similarity_threshold: 0.65
- 语义相似度计算，阈值过滤
- 支持人工确认映射关系

### 赛题结构化

支持 PDF/DOCX/DOC/TXT，输出结构化 JSON：
- questions: id, type, content, options, answer, skills, difficulty
- knowledge_nodes: id, name, description, type

---

## 四、API 接口

**认证**:
- Authorization: Bearer jwt_token
- X-Institution-ID: institution_id

**核心接口**:

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /agent/qa | 文本问答 |
| POST | /agent/video-locate | 视频定位 |
| POST | /agent/code-parse | 代码解析 |
| POST | /agent/fault-diagnosis | 故障诊断 |
| POST | /knowledge-base/upload | 资源上传 |

**响应结构**:
```json
{"answer": "...", "citations": [...], "confidence": 0.92, "processing_time_ms": 850}
```

---

## 五、非功能指标

- 检索响应 P95: ≤ 2s
- 最大 QPS: ≥ 50
- 月度可用性: ≥ 99.5%
- 赛题结构化准确率: ≥ 95%
- 数据隔离: 按院校物理隔离

---

## 六、部署方式

**院校部署流程**:
1. 创建 InstitutionConfig
2. 注册机构 (type="school")
3. 启用指定赛项
4. 健康检查

**反馈收集**:
- 用户评分 1-5
- 生成试点报告
- 自动改进建议

---

## 七、技术优势

1. **混合检索**: RRF 融合向量 + 关键词
2. **AgenticRAG**: 多步推理，自主决策
3. **多模态**: 文本/图片/表格/公式/视频
4. **领域适配**: 工艺库 + 故障案例库 + 知识图谱
5. **可部署**: 院校级隔离，完整运维

---

## 结束

以上是技术方案的全部内容，谢谢各位。