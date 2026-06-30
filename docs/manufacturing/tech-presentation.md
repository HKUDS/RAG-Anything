# RAG-Anything 智能制造智能体技术方案

---

## 一、系统架构

### 1.1 整体架构

基于 C4 模型设计，分为四层：

**L4 系统上下文**: RAG-Anything 引擎 + 智能制造领域模块 + 天工讲堂平台

**L3 容器层**:
- **知识图谱服务**: 节点/边管理、关系查询、谱系树构建
- **多模态知识管道**: 文档解析、赛题结构化、教材对齐、数据清洗
- **智能体服务**: 文本问答、故障诊断、视频定位、代码解析
- **部署运维**: 院校部署、监控指标、数据看板

**L2 组件层**:
- 知识图谱: models.py, parser.py, tagger.py, graph_api.py
- 知识管道: process_library, fault_case_library, exam_structurer, textbook_aligner
- 智能体: qa_engine, fault_diagnosis, video_locator, source_tracer

---

## 二、核心技术参数

### 2.1 RAG-Anything 引擎配置

```python
# 解析配置
parse_method: str = "auto"
parser: str = "mineru"

# 实体提取
entity_types: str = ""
entity_extraction_min_degree: int = 0

# 多模态处理开关
enable_image_processing: bool = True
enable_table_processing: bool = True
enable_equation_processing: bool = True
enable_video_processing: bool = False

# 并发控制
max_concurrent_files: int = 1
```

### 2.2 LightRAG 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| top_k | 10 | 检索返回数量 |
| chunk_token_size | - | 文本分块大小 |
| cosine_threshold | - | 余弦相似度阈值 |
| max_parallel_insert | - | 最大并行插入数 |
| max_graph_nodes | - | 最大图谱节点数 |

### 2.3 问答引擎参数

```python
# QAEngine 初始化参数
top_k: int = 10                    # 检索返回数
citation_required: bool = True     # 强制引用来源
query_mode: str = "rrf"            # RRF 融合检索
max_steps: int = 3                 # AgenticRAG 最大推理步数
```

### 2.4 故障诊断参数

```python
# FaultDiagnosisEngine
max_dialog_rounds: int = 5             # 最大对话轮数
confidence_threshold: float = 0.6      # 置信度阈值
```

### 2.5 视频定位参数

```python
# VideoLocator
frame_window: int = 3                  # 匹配帧前后窗口
min_segment_duration: float = 5.0      # 最小时长(秒)
```

---

## 三、实现方法

### 3.1 两级问答策略

**Tier 1 - 直接检索**:
1. RRF 融合检索，返回上下文
2. 上下文 ≥ 200 字符 → 直接 LLM 生成
3. 上下文 50-200 字符 → 生成后评估置信度
4. 上下文 < 50 字符 → 进入 Tier 2

**Tier 2 - AgenticRAG**:
1. ReAct 循环：思考 → 检索 → 推理 → ... → 回答
2. 最大步数 max_steps = 3
3. 注册 SearchTool，自主调用检索

### 3.2 三级图片匹配

**Tier 1 - 图号精确匹配**:
- 正则提取 "图N"、"Figure N"、"Fig.N"
- 映射到图片序列

**Tier 2 - Caption 关键字匹配**:
- jieba 分词
- 计算 query 与 caption 的关键字交集

**Tier 3 - 路径关键字匹配**:
- 从文件名/目录名提取关键字
- 交集匹配

### 3.3 故障诊断流程

1. 用户描述故障现象
2. 案例库向量匹配 (cosine similarity)
3. 基于症状选择追问模板（加工精度/表面质量/机械振动/电气故障）
4. 多轮对话缩小范围
5. 计算置信度：avg_score × 0.7 + concentration × 0.3
6. 置信度 ≥ 0.8 或轮数 ≥ 5 → 输出诊断结论

### 3.4 知识图谱构建

**节点类型**:
- competition_topic: 赛项题目
- skill_point: 技能点
- knowledge_point: 知识点
- tool: 工具设备
- standard: 标准规范

**关系类型**:
- requires: 前置依赖
- advances_to: 后续进阶
- related_to: 关联知识
- evaluates: 评分关联
- applies_in: 应用场景

### 3.5 教材对齐算法

```python
# 语义相似度计算
similarity_threshold: float = 0.65

# 对齐流程
1. 输入: textbook_knowledge[], competition_skills[]
2. 对每个教材知识点，遍历所有赛项能力
3. 计算语义相似度 (cosine)
4. 取最高匹配，阈值过滤
5. 输出映射列表，支持人工确认
```

### 3.6 赛题结构化

**支持格式**: PDF, DOCX, DOC, TXT

**输出结构**:
```json
{
  "metadata": {"competition_track", "processed_at", "total_questions"},
  "questions": [{"id", "question_type", "content", "options", 
                 "correct_answer", "skill_requirements", "difficulty"}],
  "knowledge_nodes": [{"id", "name", "description", "node_type"}]
}
```

---

## 四、API 接口

### 4.1 认证方式

```
Header:
  Authorization: Bearer <jwt_token>
  X-Institution-ID: <institution_id>
```

### 4.2 核心接口

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/v1/manufacturing/agent/qa | 文本问答 |
| POST | /api/v1/manufacturing/agent/video-locate | 视频片段定位 |
| POST | /api/v1/manufacturing/agent/code-parse | 代码解析 |
| POST | /api/v1/manufacturing/agent/fault-diagnosis | 故障诊断 |
| GET | /api/v1/manufacturing/knowledge-graph/nodes | 获取知识节点 |
| POST | /api/v1/manufacturing/knowledge-base/upload | 上传多模态资源 |

### 4.3 问答响应结构

```json
{
  "answer": "...",
  "citations": [{"source_title": "...", "page": 42, "excerpt": "..."}],
  "confidence": 0.92,
  "processing_time_ms": 850
}
```

---

## 五、非功能指标

| 指标 | 目标值 |
|------|--------|
| 检索响应 P95 | ≤ 2s |
| 最大 QPS | ≥ 50 |
| 月度可用性 | ≥ 99.5% |
| 赛题结构化准确率 | ≥ 95% |
| 数据隔离 | 按院校物理隔离 |

---

## 六、部署方式

### 6.1 院校部署流程

```python
# SchoolDeployer.deploy()
1. 创建 InstitutionConfig
2. 注册机构信息 (institution_type="school")
3. 启用指定赛项 tracks
4. 健康检查
5. 返回部署状态
```

### 6.2 反馈收集

支持用户评分 (1-5)，生成试点报告，包含改进建议。

---

## 七、技术优势

1. **混合检索**: RRF 融合向量检索与关键词检索
2. **AgenticRAG**: 多步推理，自主决策
3. **多模态支持**: 文本/图片/表格/公式/视频
4. **领域适配**: 智能制造专业知识图谱 + 工艺库 + 故障案例库
5. **可部署**: 支持院校级隔离部署，完整运维监控