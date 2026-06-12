# 智能制造专业智能体 — 知识库数据目录

## 目录结构

```
data/manufacturing_kb/
├── README.md           # 本文件
├── exams/              # 赛题文档 (PDF/Word)
│   └── structured.json # 导入后的结构化数据
├── fault_cases/        # 故障案例 (JSON)
│   ├── sample.json     # 示例数据
│   └── cases.json      # 导入后的案例库索引
├── processes/          # 工艺文档 (TXT/MD/DOCX)
│   └── _index.json     # 导入后的工艺库索引
├── textbooks/          # 教材知识点 (CSV)
│   └── aligned.json    # 导入后的对齐映射
├── metrics/            # 运维指标数据
└── dashboard/          # 看板快照
```

## 数据导入流程

### 1. 导入赛题数据

```bash
# 将赛题 PDF/Word 放入 exams/ 目录
python scripts/import_exams.py --input ./data/manufacturing_kb/exams/ --track machining
```

### 2. 导入故障案例

```bash
# 准备 JSON 文件 (格式见 sample.json)
python scripts/import_fault_cases.py --input ./data/manufacturing_kb/fault_cases/sample.json
```

### 3. 导入工艺文档

```bash
# 将工艺文档放入 processes/ 目录
python scripts/import_processes.py --input ./data/manufacturing_kb/processes/
```

### 4. 导入教材知识点

```bash
# 准备 CSV 文件 (columns: chapter, knowledge_point, description)
python scripts/import_textbook_kps.py --csv ./data/manufacturing_kb/textbooks/sample.csv --track machining
```

## 数据格式说明

### 故障案例 JSON 格式

```json
[
  {
    "title": "案例标题",
    "equipment_type": "数控铣床",
    "fault_category": "机械",
    "phenomenon": "故障现象描述",
    "root_cause": "根本原因分析",
    "troubleshooting_steps": ["步骤1", "步骤2"],
    "preventive_measures": ["预防措施1"],
    "severity": "medium"
  }
]
```

必填字段: `title`, `phenomenon`, `root_cause`, `troubleshooting_steps`

### 教材知识点 CSV 格式

```csv
chapter,knowledge_point,description
第1章 数控加工基础,数控铣削基本原理,介绍数控铣削的工作原理和基本概念
第1章 数控加工基础,切削三要素,切削速度、进给量和切削深度的选择原则
```
