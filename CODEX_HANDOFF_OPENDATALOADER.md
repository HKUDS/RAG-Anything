# OpenDataLoader PDF 解析器集成 — Codex 接手说明

> 为 RAG-Anything 项目新增 OpenDataLoader PDF 2.5.0 解析器后端。
> 本文件供 OpenAI Codex / 其他编码智能体继续推进剩余任务使用。

---

## 1. 项目概况

**项目名称**：RAG-Anything（基于 LightRAG 的多模态文档知识库系统）

**任务**：集成 [OpenDataLoader PDF 2.5.0](https://github.com/opendataloader-project/opendataloader-pdf) 作为可选的 PDF 专用解析器后端。

**当前分支**：`feature/custom-enhancements`

**核心设计理念**：不替换现有默认解析器。通过新增 `PDF_PARSER=opendataloader` 配置项，仅对 `.pdf` 文件使用 OpenDataLoader，其他格式（`.docx`、图片等）继续走原来的全局 `PARSER` 设置。

---

## 2. 已完成的工作

### 2.1 文件清单

| 文件 | 状态 | 角色 |
|------|------|------|
| `raganything/parser/opendataloader_parser.py` | **新建** (~500行) | 核心解析器适配器 |
| `raganything/parser/__init__.py` | **修改** | 注册 `opendataloader` 为第 5 个内置解析器 |
| `raganything/config.py` | **修改** | 新增 `pdf_parser` 配置字段 |
| `raganything/processor/doc_processor.py` | **修改** | PDF 覆盖路由 + 页面覆盖门控泛化 + 缓存身份 |
| `process_worker.py` | **修改** | 子进程配置传播 `pdf_parser` |
| `tests/test_opendataloader_parser.py` | **新建** (~380行) | 50 个单元/合约测试 |
| `tests/test_custom_parser.py` | **修改** | 内置解析器数量断言 4→5 |
| `env.example` | **修改** | 文档化 5 个新环境变量 |
| `reproduce/data/contract_spike.py` | **新建** (~280行) | SDK 合约验证脚本（一次性） |

### 2.2 核心实现细节

#### OpenDataLoaderParser 适配器 (`opendataloader_parser.py`)

```
类层次：OpenDataLoaderParser → Parser (base.py)

公开方法：
  check_installation()  → 验证 Java 17 + Python 包，不联网
  parse_pdf()           → 唯一入口，拒绝非 PDF 文件
  parse_document()      → 委托到 parse_pdf()
  cache_identity()      → 返回 "opendataloader|2.5.0|schema_v1|local_fast"
  supports_pdf_coverage → 返回 True

转换流程：
  1. 预检查（文件大小/页数限制）
  2. 创建唯一输出目录 (_unique_output_dir)
  3. 调用 opendataloader_pdf.convert()（仅 fast 本地模式）
  4. 发现并加载 JSON 工件
  5. Schema 验证
  6. 递归展平 kids 树 → 统一内容块
  7. 构建 PageTrackedContent 页面覆盖清单
  8. 原子写入 provenance 侧车文件 (_provenance.json)

错误类型层级：
  ODLPreflightError      → Java/包/环境问题
  ODLConversionError     → SDK 执行异常
  ODLValidationError     → 输出格式不符
  ODLPageCoverageError   → 页面覆盖不完整
  ODLContainerError      → 路径逃逸
```

#### 技术关键点

1. **JSON Schema**：上游输出为递归 `kids` 树形结构（非扁平数组），元素通过 `page number` 字段关联页面
2. **Bbox 坐标系**：`[left, bottom, right, top]`，PDF points 单位，左下角原点 → 适配器统一标准化为此格式
3. **页面覆盖验证**：上游不提供显式逐页成功/失败标记。缓解方案：交叉比对 `number_of_pages` 与 `pypdf` 源页数，空白页视为已覆盖（零元素），依赖 JVM 退出码判断整体成败
4. **PageTrackedContent**：带 `page_coverage` 元数据的列表子类，包含 `successful_pages`、`failed_pages`、`skipped_pages`、`blank_pages` 四个集合
5. **路径安全**：所有媒体引用强制验证在解析器输出目录内，拒绝 `../` 穿越和符号链接逃逸
6. **缓存身份**：`cache_identity()` 包含后端名 + 包版本 + Schema 版本 + 模式，版本/模式变更自动使缓存失效

#### 解析器注册表 (`__init__.py`)

```
SUPPORTED_PARSERS = ("mineru", "docling", "paddleocr", "marker", "opendataloader")

get_parser("opendataloader") → 懒加载 _get_odl_parser() → OpenDataLoaderParser()
```

`opendataloader` 通过懒加载实现：不导入 SDK 直到实际调用。`_get_odl_parser()` 返回全新实例，避免配置跨文档污染。

#### 页面覆盖门控泛化 (`doc_processor.py`)

```python
# 改前（硬编码）
if parser == "docling":
    ...

# 改后（能力检查）
_PARSERS_WITH_PDF_COVERAGE = frozenset({"docling", "opendataloader"})

def _parser_supports_pdf_coverage(self, parser) -> bool:
    return hasattr(parser, 'supports_pdf_coverage') and parser.supports_pdf_coverage
```

`blank_pages` 视为已覆盖（成功的空白页），不计入失败。

#### PDF 解析器路由 (`doc_processor.py`)

```python
# 有效解析器选择逻辑
if file_ext == '.pdf' and self.config.pdf_parser:
    effective_parser = self.config.pdf_parser  # 使用 PDF 专用解析器
else:
    effective_parser = self.config.parser       # 使用全局解析器
```

### 2.3 配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PDF_PARSER` | (空) | 设为 `opendataloader` 启用。空 = 所有格式走全局 `PARSER` |
| `ODL_TIMEOUT` | `600` | 解析器超时秒数 |
| `ODL_JAVA_HEAP` | `-Xmx2g` | Java 堆内存限制 |
| `ODL_MAX_PAGES` | `500` | 最大 PDF 页数 |
| `ODL_MAX_BYTES` | `209715200` | 最大文件大小（200 MiB） |

### 2.4 测试结果

```
84 passed, 1 skipped, 1 warning — 5.47s — 零回归
```

覆盖：注册、安装探测、负向测试、bbox 归一化、标题深度、元素展平、页面覆盖、缓存身份、注册表接线、覆盖门控、缓存键身份、原子 JSON 写入。

`openspec validate add-opendataloader-pdf-parser --strict` → **通过**。

---

## 3. 未完成的剩余任务

### 高优先级（基础设施）

| 任务 | 内容 | 文件 |
|------|------|------|
| **1.1** | SBOM 生成（CycloneDX/SPDX），许可证对账（含 veraPDF 版本差异确认），缺失/未知许可证不得分发 | pyproject.toml, 新 SBOM 文件 |
| **1.2** | `pyproject.toml` 添加 `[project.optional-dependencies]` 的 `opendataloader` extra，固定 `opendataloader-pdf==2.5.0` 及哈希，更新 `uv.lock` | pyproject.toml, uv.lock |
| **1.3** | Dockerfile 添加 opt-in 构建目标：安装 JRE 17 headless + opendataloader extra。默认镜像保持原样 | Dockerfile |
| **1.4** | 保留 LICENSE、NOTICE、第三方声明文件于固定路径 | 文档/打包 |

### 中优先级（测试与验证）

| 任务 | 内容 |
|------|------|
| **1.7** | 基于部署容量确定保守的金丝雀限制 |
| **4.6** | Worker/任务级集成测试（配置传播、超时、重试等） |
| **4.7** | 安全回归测试（注入防线验证） |
| **4.8** | 需要 Java + 真实 PDF 的集成测试（标记 skip） |
| **4.9** | 容器构建测试（默认 + opt-in 变体） |
| **3.8** | 结构化日志/指标（后端、版本、页数、耗时、结果分类） |

### 低优先级（文档与评估）

| 任务 | 内容 |
|------|------|
| **5.1** | 完整部署文档 |
| **5.2** | 30-50 份中文 PDF 金标语料准备 |
| **5.3** | 与 Docling/MinerU 的金丝雀对比评估 |
| **5.4** | go/no-go 证据收集 |
| **5.5** | 隔离 staging 部署 |
| **5.6** | 回滚演练 |

---

## 4. 本机环境信息

- **OS**: Windows 11 Home China
- **Java**: JRE 17 安装于 `D:\Java\jre17\`
- **Python venv**: 项目 `.venv/`，需手动复制 `opendataloader_pdf` 到 `.venv/Lib/site-packages/`
- **当前分支**: `feature/custom-enhancements`
- **主分支**: `main`

---

## 5. 快速开始（Codex 如何继续）

```bash
# 1. 确认环境
cd c:\Users\98014\知元
git branch  # 应显示 feature/custom-enhancements
git status  # 查看未提交变更

# 2. 运行现有测试确认基线
.venv\Scripts\python.exe -m pytest tests/test_opendataloader_parser.py -v --no-header
.venv\Scripts\python.exe -m pytest tests/test_custom_parser.py -v --no-header

# 3. 阅读设计文档
cat openspec\changes\add-opendataloader-pdf-parser\design.md
cat openspec\changes\add-opendataloader-pdf-parser\tasks.md

# 4. 继续推进剩余任务（建议从 1.2 pyproject.toml 开始）
```

---

## 6. 关键参考

- OpenSpec 变更目录：`openspec/changes/add-opendataloader-pdf-parser/`
- 设计文档：`openspec/changes/add-opendataloader-pdf-parser/design.md`
- 任务清单：`openspec/changes/add-opendataloader-pdf-parser/tasks.md`
- 上游 SDK：https://github.com/opendataloader-project/opendataloader-pdf
- PyPI 包：`opendataloader-pdf==2.5.0`
- 合约探针：`reproduce/data/contract_spike.py`（验证 SDK 输出结构的脚本）

---

*生成时间：2026-07-24 | 生成者：Claude Code | 目标接收者：OpenAI Codex / 后续编码智能体*
