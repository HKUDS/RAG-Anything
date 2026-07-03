# Design: manufacturing → autorepair 全量映射

## 架构总览

```
重命名前                                 重命名后
─────────────────────────────────       ─────────────────────────────────
raganything/manufacturing/              raganything/autorepair/
  __init__.py                             __init__.py
  agent/                                  agent/
    api.py              (AgenticRAG)        api.py
    qa_engine.py        (问答引擎)          qa_engine.py
    code_parser.py      (代码解析)          code_parser.py
    fault_diagnosis.py  (故障诊断)          fault_diagnosis.py
    source_tracer.py    (来源追溯)          source_tracer.py
    lineage_pusher.py   (谱系推送)          lineage_pusher.py
    video_locator.py    (视频定位)          video_locator.py
    deployment_config.py(部署配置)          deployment_config.py
  knowledge_graph/                        knowledge_graph/
    graph_api.py        (图谱API)           graph_api.py
    models.py           (数据模型)          models.py
    parser.py           (解析器)            parser.py
    tagger.py           (标引器)            tagger.py
  knowledge_pipeline/                     knowledge_pipeline/
    data_cleaner.py                        data_cleaner.py
    exam_structurer.py                     exam_structurer.py
    fault_case_library.py                  fault_case_library.py
    process_library.py                     process_library.py
    resource_annotator.py                  resource_annotator.py
    scoring_digitizer.py                   scoring_digitizer.py
    textbook_aligner.py                    textbook_aligner.py
    copyright_reviewer.py                  copyright_reviewer.py
  deployment/                             deployment/
    dashboard.py                           dashboard.py
    enterprise_adapter.py                  enterprise_adapter.py
    ops_monitor.py                         ops_monitor.py
    school_deployer.py                     school_deployer.py
    test_harness.py                        test_harness.py
    tiangong_platform.py                   tiangong_platform.py

frontend/src/pages/                      frontend/src/pages/
  ManufacturingAgentPage.jsx               AutoRepairAgentPage.jsx
  ManufacturingDashboardPage.jsx           AutoRepairDashboardPage.jsx
  ManufacturingKnowledgePage.jsx           AutoRepairKnowledgePage.jsx

frontend/src/components/                 frontend/src/components/
  ManufacturingKBSelector.jsx              AutoRepairKBSelector.jsx

frontend/src/hooks/                      frontend/src/hooks/
  useManufacturingKB.js                    useAutoRepairKB.js
```

## 详细映射表

### 1. 路由映射

| 原路由 | 新路由 |
|--------|--------|
| `/manufacturing` | `/autorepair` |
| `/manufacturing/knowledge` | `/autorepair/knowledge` |
| `/manufacturing/agent` | `/autorepair/agent` |
| `/api/manufacturing/qa/stream` | `/api/autorepair/qa/stream` |
| `/api/manufacturing/code/parse` | `/api/autorepair/code/parse` |
| `/api/manufacturing/fault-diagnosis` | `/api/autorepair/fault-diagnosis` |
| `/api/manufacturing/fault-diagnosis/continue` | `/api/autorepair/fault-diagnosis/continue` |
| `/api/manufacturing/dashboard` | `/api/autorepair/dashboard` |
| `/api/manufacturing/kb-list` | `/api/autorepair/kb-list` |
| `/api/manufacturing/knowledge-graph/*` | `/api/autorepair/knowledge-graph/*` |
| `/api/manufacturing/institutions` | `/api/autorepair/institutions` |
| `/api/manufacturing/health` | `/api/autorepair/health` |
| `/api/manufacturing/process-library/*` | `/api/autorepair/process-library/*` |
| `/api/manufacturing/fault-cases/*` | `/api/autorepair/fault-cases/*` |

### 2. 权限映射

| 原权限 | 新权限 |
|--------|--------|
| `manufacturing:read` | `autorepair:read` |
| `manufacturing:write` | `autorepair:write` |

### 3. Python 类/函数映射

| 原名称 | 新名称 |
|--------|--------|
| `_get_manufacturing()` | `_get_autorepair()` |
| `_get_mfg_graph(kb)` | `_get_autorepair_graph(kb)` |
| `_manufacturing_components` | `_autorepair_components` |
| `ManufacturingQuery` | `AutoRepairQuery` |
| `MfgAgentQuery` | `AutoRepairAgentQuery` |
| `MfgLLMAdapter` | `AutoRepairLLMAdapter` |
| `class ManufacturingAgent` | `class AutoRepairAgent` |
| `process_manufacturing_qa` | `process_autorepair_qa` |
| `KnowledgeGraphAPI` | (不变，通用) |
| `LightRAGGraphStore` | (不变，通用) |

### 4. 前端组件/Hook 映射

| 原名称 | 新名称 |
|--------|--------|
| `ManufacturingAgentPage` | `AutoRepairAgentPage` |
| `ManufacturingDashboardPage` | `AutoRepairDashboardPage` |
| `ManufacturingKnowledgePage` | `AutoRepairKnowledgePage` |
| `ManufacturingKBSelector` | `AutoRepairKBSelector` |
| `useManufacturingKB` | `useAutoRepairKB` |
| `manufacturingKb` (localStorage key) | `autorepair_kb` |

### 5. UI 文案映射（关键用户可见变化）

| 原文案 | 新文案 |
|--------|--------|
| 制造智能体 | 汽修智能助手 |
| 智能问答 · 代码解析 · 故障诊断 | 维修问答 · 故障码解析 · 故障诊断 |
| 仪表板 | 诊断看板 |
| 制造知识库 | 汽修知识库 |
| 输入你的制造领域问题... | 输入汽车维修问题... |
| 数控铣削的切削参数如何选择？ | 发动机怠速抖动如何诊断？ |
| PLC 程序梯形图设计原则 | 自动变速箱故障码 P0730 解析 |
| 如何检测加工中心的定位精度？ | 如何检测氧传感器信号异常？ |
| 粘贴 G 代码或 PLC 程序进行分析 | 粘贴 OBD 故障码或 ECU 数据流进行分析 |
| 支持 G 代码语法高亮、指令解释与风险检测 | 支持 OBD 故障码解析、数据流分析与风险检测 |
| G 代码 | OBD 故障码 (DTC) |
| PLC 指令表 | ECU 数据流 |
| 描述设备故障现象... | 描述车辆故障现象... |
| 加工精度超差，误差约0.05mm | 发动机故障灯亮，怠速不稳 |
| 主轴运转时有异常振动 | 刹车时有异响，制动距离变长 |
| PLC 输出信号无响应 | 空调压缩机不工作 |
| 知识库 | 汽修知识库 |
| 图谱可视化 | 图谱可视化 (不变) |
| 节点列表 | 节点列表 (不变) |
| 故障案例库 | 故障案例库 (不变) |
| 企业工艺库 | 维修工艺库 |
| 新建制造领域知识库 | 新建汽修知识库 |
| 输入子领域名称，如：焊接工艺 | 输入子领域名称，如：发动机系统 |

### 6. 数据库迁移

```sql
-- 迁移 PRE-MIGRATION: 记录当前状态
SELECT role_name, permissions FROM roles WHERE 'manufacturing:read' = ANY(permissions);

-- 迁移: 更新权限字符串
UPDATE roles 
SET permissions = array_replace(permissions, 'manufacturing:read', 'autorepair:read')
WHERE 'manufacturing:read' = ANY(permissions);

UPDATE roles 
SET permissions = array_replace(permissions, 'manufacturing:write', 'autorepair:write')
WHERE 'manufacturing:write' = ANY(permissions);

-- 迁移 POST-VERIFY
SELECT role_name, permissions FROM roles WHERE 'autorepair:read' = ANY(permissions);
```

### 7. 前端 localStorage 迁移

```js
// useAutoRepairKB.js 中自动迁移旧 key
const stored = localStorage.getItem('autorepair_kb')
if (!stored) {
  const legacy = localStorage.getItem('mfg_kb')
  if (legacy && legacy !== 'default') {
    localStorage.setItem('autorepair_kb', legacy)
    localStorage.removeItem('mfg_kb')
  }
}
```

## 实施阶段

### Phase 1: 后端 Python 模块重命名
- 重命名 `raganything/manufacturing/` → `raganything/autorepair/`
- 更新所有内部 import 路径
- 更新 `raganything/permissions.py` 权限常量
- 更新 `raganything/routers/manufacturing.py` → `autorepair.py`
- 更新 `server.py` 中的路由注册

### Phase 2: 前端重命名
- 重命名页面/组件/Hook 文件
- 更新所有 import 路径
- 更新路由和导航
- 改写所有 UI 文案

### Phase 3: 数据库迁移
- 创建权限迁移 SQL 脚本
- 在部署前执行

### Phase 4: 清理与验证
- 更新脚本/测试文件中的引用
- 全量构建验证
- 端到端回归测试
