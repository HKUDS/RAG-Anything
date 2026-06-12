# Data Import Tools

## Purpose

提供智能制造专业智能体的数据导入工具集，支持大赛赛题、故障案例、工艺文档和教材知识点的批量导入，将非结构化数据转化为结构化知识库内容。

## Requirements

### Requirement: 赛题批量导入
系统 SHALL 提供 CLI 脚本 `scripts/import_exams.py`，支持批量导入大赛赛题 PDF/Word 文件，自动提取题目、答案、评分标准、技能要求，并创建知识图谱节点。

#### Scenario: 批量导入赛题文件夹
- **WHEN** 用户执行 `python scripts/import_exams.py --input ./exams/machining/ --track machining`
- **THEN** 系统 SHALL 遍历目录下所有 PDF/Word 文件，逐个解析并结构化入库，输出导入报告（成功/失败/跳过数量）

#### Scenario: 断点续传
- **WHEN** 导入过程中断（Ctrl+C 或异常）
- **THEN** 再次执行相同命令时，系统 SHALL 跳过已入库的文件，仅处理未导入的文件

### Requirement: 工艺文档导入
系统 SHALL 提供 `scripts/import_processes.py`，支持导入企业工艺文档，自动分类并提取工艺参数。

#### Scenario: 单文件导入
- **WHEN** 执行 `python scripts/import_processes.py --file process_001.docx`
- **THEN** 系统 SHALL 自动分类工艺类型，提取参数表，输出入库确认

### Requirement: 故障案例导入
系统 SHALL 提供 `scripts/import_fault_cases.py`，支持从 JSON 文件批量导入故障案例。

#### Scenario: JSON 批量导入
- **WHEN** 执行 `python scripts/import_fault_cases.py --input ./faults/batch1.json`
- **THEN** 系统 SHALL 解析 JSON 中的案例数组，验证必填字段，逐条入库并输出统计

#### Scenario: 必填字段校验
- **WHEN** 案例 JSON 缺少 `phenomenon` 或 `root_cause` 字段
- **THEN** 该条案例 SHALL 被跳过并记录到错误日志

### Requirement: 教材知识点导入
系统 SHALL 提供 `scripts/import_textbook_kps.py`，支持从 CSV 文件导入教材知识点并自动对齐赛项能力。

#### Scenario: CSV 导入并自动对齐
- **WHEN** 执行 `python scripts/import_textbook_kps.py --csv textbook.csv --track machining`
- **THEN** 系统 SHALL 逐行解析知识点，自动计算与赛项能力的语义相似度，建立待确认映射关系
