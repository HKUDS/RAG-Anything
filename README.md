# PPT-RAG：多模态 RAG 实践仓库

一个面向真实文档场景的多模态 RAG 项目，覆盖“文档解析 -> 多模态理解 -> 检索问答 -> Web 交互 -> 批处理与离线部署”完整链路。

本仓库当前分支已包含：
- 面向单文档工作流的 Streamlit WebUI（内置检索与智能问答循环）
- 文本/图像/表格/公式一体化处理能力
- 批量文档处理与 Dry-Run 预检查
- 上下文增强的多模态内容理解
- 增强版 Markdown 转 PDF
- 离线环境运行（本地 tokenizer 缓存）
- 独立图像编辑 CLI（基于 DashScope 异步接口）

---

## 1. 功能概览

### 1.1 核心能力
- 多格式输入：PDF、Office（doc/docx/ppt/pptx/xls/xlsx）、图片、txt、md
- 多模态处理：图像、表格、公式与正文协同建模
- 混合检索：结合向量检索与图关系检索
- 智能问答：可结合工具调用进行复杂问题求解

### 1.2 工程能力
- 批处理并发执行、进度可视化、错误回收
- 可配置上下文窗口，提高图表/公式语义理解质量
- 可选 Markdown 高质量 PDF 输出
- 支持弱网/离线场景初始化

---

## 2. 快速开始

### 2.1 环境准备
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -e .
```

### 2.2 配置环境变量
```bash
cp env.example .env
```

至少补充以下关键项：
- `OPENAI_API_KEY` 或兼容模型服务密钥
- `OPENAI_BASE_URL`（如使用兼容网关）
- `TEXT_LLM_MODEL`
- `VISION_LLM_MODEL`
- `EMBEDDING_MODEL`

### 2.3 启动 WebUI
```bash
streamlit run app.py
```

默认入口为本地 Streamlit 页面，可上传文档并进行多轮问答。

---

## 3. 目录说明

- `app.py`：Streamlit 主应用，包含文档上传、索引构建、检索问答与会话逻辑
- `examples/`：覆盖批处理、内容直插、格式测试、上下文增强等示例
- `docs/`：批处理、上下文配置、增强 Markdown、离线部署说明
- `scripts/create_tiktoken_cache.py`：离线 tokenizer 缓存生成脚本
- `image.py`：独立图像编辑命令行工具

---

## 4. 常用运行方式

### 4.1 示例脚本
```bash
python examples/batch_processing_example.py
python examples/insert_content_list_example.py
python examples/batch_dry_run_example.py
```

### 4.2 批处理（命令行）
```bash
python examples/batch_processing_example.py
python examples/batch_dry_run_example.py
```

### 4.3 图像编辑 CLI
```bash
export DASHSCOPE_API_KEY="<your_key>"
python image.py \
  --image ./data/agent_loop.png \
  --prompt "提升画面层次与视觉冲击力，保留主体构图" \
  --output ./output/agent_loop_vivid.png
```

---

## 5. 关键配置项（节选）

`.env` 中常见参数：
- 解析与处理：`PARSER`、`PARSE_METHOD`、`ENABLE_IMAGE_PROCESSING`、`ENABLE_TABLE_PROCESSING`、`ENABLE_EQUATION_PROCESSING`
- 检索参数：`RETRIEVE_TOP_K`、`RETRIEVE_CHUNK_TOP_K`
- 上下文增强：`CONTEXT_WINDOW`、`CONTEXT_MODE`、`MAX_CONTEXT_TOKENS`
- 存储目录：`OUTPUT_DIR`、`DOC_STORE_DIR`、`WORKING_DIR_ROOT`

建议先保留默认值，完成端到端跑通后再按数据规模与模型成本调优。

---

## 6. 文档导航

- 批处理说明：`docs/batch_processing.md`
- 上下文增强：`docs/context_aware_processing.md`
- 增强 Markdown：`docs/enhanced_markdown.md`
- 离线部署：`docs/offline_setup.md`

---

## 7. 已知依赖说明

- Office 文档处理依赖系统级 LibreOffice
- 增强 Markdown 的某些后端可能需要额外系统包（见 `docs/enhanced_markdown.md`）
- 离线模式需提前生成本地 tokenizer 缓存（见 `docs/offline_setup.md`）

---

## 8. 许可证

本项目采用 MIT 许可证，详见 `LICENSE`。
