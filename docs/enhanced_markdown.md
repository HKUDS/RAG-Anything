# 增强 Markdown 转换

本文档描述了 RAG-Anything 的增强 Markdown 转换功能，该功能提供从 Markdown 文件到高质量 PDF 的生成，支持多种后端选项和高级样式设置。

## 概述

增强 Markdown 转换功能提供从 Markdown 文件生成专业品质的 PDF。它支持多种转换后端、高级样式选项、语法高亮，并与 RAG-Anything 的文档处理管道无缝集成。

## 主要特性

- **多种后端**：WeasyPrint、Pandoc 和自动后端选择
- **高级样式**：自定义 CSS、语法高亮和专业布局
- **图像支持**：嵌入图像，具有适当的缩放和定位
- **表格支持**：格式化的表格，带有边框和专业样式
- **代码高亮**：使用 Pygments 为代码块提供语法高亮
- **自定义模板**：支持自定义 CSS 和文档模板
- **目录**：自动生成带有导航链接的目录
- **专业排版**：高质量字体和间距

## 安装

### 必需依赖

```bash
# 基础安装
pip install raganything[all]

# 增强 Markdown 转换所需
pip install markdown weasyprint pygments
```

### 可选依赖

```bash
# Pandoc 后端（需要系统安装）
# Ubuntu/Debian:
sudo apt-get install pandoc wkhtmltopdf

# macOS:
brew install pandoc wkhtmltopdf

# 或使用 conda:
conda install -c conda-forge pandoc wkhtmltopdf
```

### 后端特定安装

#### WeasyPrint（推荐）
```bash
# 安装 WeasyPrint 及系统依赖
pip install weasyprint

# Ubuntu/Debian 系统依赖:
sudo apt-get install -y build-essential python3-dev python3-pip \
    python3-setuptools python3-wheel python3-cffi libcairo2 \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    libffi-dev shared-mime-info
```

#### Pandoc
- 从此处下载：https://pandoc.org/installing.html
- 需要系统级安装
- 用于复杂文档结构和 LaTeX 质量输出

## 使用方法

### 基本转换

```python
from raganything.enhanced_markdown import EnhancedMarkdownConverter, MarkdownConfig

# 使用默认设置创建转换器
converter = EnhancedMarkdownConverter()

# 将 Markdown 文件转换为 PDF
success = converter.convert_file_to_pdf(
    input_path="document.md",
    output_path="document.pdf",
    method="auto"  # 自动选择最佳可用后端
)

if success:
    print("✅ 转换成功！")
else:
    print("❌ 转换失败")
```

### 高级配置

```python
# 创建自定义配置
config = MarkdownConfig(
    page_size="A4",           # A4、Letter、Legal 等
    margin="1in",             # CSS 样式边距
    font_size="12pt",         # 基础字体大小
    line_height="1.5",        # 行间距
    include_toc=True,         # 生成目录
    syntax_highlighting=True, # 启用代码语法高亮

    # 自定义 CSS 样式
    custom_css="""
    body {
        font-family: 'Georgia', serif;
        color: #333;
    }
    h1 {
        color: #2c3e50;
        border-bottom: 2px solid #3498db;
        padding-bottom: 0.3em;
    }
    code {
        background-color: #f8f9fa;
        padding: 2px 4px;
        border-radius: 3px;
    }
    pre {
        background-color: #f8f9fa;
        border-left: 4px solid #3498db;
        padding: 15px;
        border-radius: 5px;
    }
    table {
        border-collapse: collapse;
        width: 100%;
        margin: 1em 0;
    }
    th, td {
        border: 1px solid #ddd;
        padding: 8px 12px;
        text-align: left;
    }
    th {
        background-color: #f2f2f2;
        font-weight: bold;
    }
    """
)

converter = EnhancedMarkdownConverter(config)
```

### 后端选择

```python
# 检查可用后端
converter = EnhancedMarkdownConverter()
backend_info = converter.get_backend_info()

print("可用后端:")
for backend, available in backend_info["available_backends"].items():
    status = "✅" if available else "❌"
    print(f"  {status} {backend}")

print(f"推荐后端: {backend_info['recommended_backend']}")

# 使用特定后端
converter.convert_file_to_pdf(
    input_path="document.md",
    output_path="document.pdf",
    method="weasyprint"  # 或 "pandoc"、"pandoc_system"、"auto"
)
```

### 内容转换

```python
# 直接转换 Markdown 内容（不从文件读取）
markdown_content = """
# 示例文档

## 介绍
这是一个**粗体**声明，带有*斜体*文本。

## 代码示例
```python
def hello_world():
    print("Hello, World!")
    return "Success"
```

## 表格
| 功能 | 状态 | 备注 |
|---------|--------|-------|
| PDF 生成 | ✅ | 正常工作 |
| 语法高亮 | ✅ | Pygments |
| 自定义 CSS | ✅ | 完全支持 |
"""

success = converter.convert_markdown_to_pdf(
    markdown_content=markdown_content,
    output_path="sample.pdf",
    method="auto"
)
```

### 命令行界面

```bash
# 基本转换
python -m raganything.enhanced_markdown document.md --output document.pdf

# 使用特定后端
python -m raganything.enhanced_markdown document.md --method weasyprint

# 使用自定义 CSS 文件
python -m raganything.enhanced_markdown document.md --css custom_style.css

# 显示后端信息
python -m raganything.enhanced_markdown --info

# 帮助
python -m raganything.enhanced_markdown --help
```

## 后端比较

| 后端 | 优点 | 缺点 | 最适合 | 质量 |
|---------|------|------|----------|---------|
| **WeasyPrint** | • 出色的 CSS 支持<br>• 快速渲染<br>• 优秀的网页风格布局<br>• 基于 Python | • 有限的 LaTeX 功能<br>• 需要系统依赖 | • 网页风格文档<br>• 自定义样式<br>• 快速转换 | ⭐⭐⭐⭐ |
| **Pandoc** | • 广泛的功能<br>• LaTeX 质量输出<br>• 学术格式<br>• 多种输入/输出格式 | • 较慢的转换<br>• 系统安装<br>• 复杂设置 | • 学术论文<br>• 复杂文档<br>• 出版质量 | ⭐⭐⭐⭐⭐ |
| **Auto** | • 自动选择<br>• 回退支持<br>• 用户友好 | • 可能不使用最佳后端 | • 通用用途<br>• 快速设置<br>• 开发 | ⭐⭐⭐⭐ |

## 配置选项

### MarkdownConfig 参数

```python
@dataclass
class MarkdownConfig:
    # 页面布局
    page_size: str = "A4"              # A4、Letter、Legal、A3 等
    margin: str = "1in"                # CSS 边距格式
    font_size: str = "12pt"            # 基础字体大小
    line_height: str = "1.5"           # 行间距倍数

    # 内容选项
    include_toc: bool = True           # 生成目录
    syntax_highlighting: bool = True   # 启用代码高亮
    image_max_width: str = "100%"      # 最大图像宽度
    table_style: str = "..."           # 默认表格 CSS

    # 样式
    css_file: Optional[str] = None     # 外部 CSS 文件路径
    custom_css: Optional[str] = None   # 内联 CSS 内容
    template_file: Optional[str] = None # 自定义 HTML 模板

    # 输出选项
    output_format: str = "pdf"         # 目前仅支持 PDF
    output_dir: Optional[str] = None   # 输出目录

    # 元数据
    metadata: Optional[Dict[str, str]] = None  # 文档元数据
```

### 支持的 Markdown 功能

#### 基本格式
- **标题**：`# ## ### #### ##### ######`
- **强调**：`*斜体*`、`**粗体**`、`***粗斜体***`
- **链接**：`[文本](url)`、`[文本][ref]`
- **图像**：`![alt](url)`、`![alt][ref]`
- **列表**：有序和无序，嵌套
- **引用**：`> 引用`
- **换行**：双空格或 `\n\n`

#### 高级功能
- **表格**：GitHub 风格表格，支持对齐
- **代码块**：围栏代码块，支持语言规范
- **内联代码**：`反引号代码`
- **水平线**：`---` 或 `***`
- **脚注**：`[^1]` 引用
- **定义列表**：术语和定义对
- **属性**：`{#id .class key=value}`

#### 代码高亮

```markdown
```python
def example_function():
    """这将被语法高亮"""
    return "Hello, World!"
```

```javascript
function exampleFunction() {
    // 这也将被高亮
    return "Hello, World!";
}
```
```

## 与 RAG-Anything 集成

增强 Markdown 转换与 RAG-Anything 无缝集成：

```python
from raganything import RAGAnything

# 初始化 RAG-Anything
rag = RAGAnything()

# 处理 Markdown 文件 - 自动使用增强转换
await rag.process_document_complete("document.md")

# 使用增强 Markdown 转换的批量处理
result = rag.process_documents_batch(
    file_paths=["doc1.md", "doc2.md", "doc3.md"],
    output_dir="./output"
)

# .md 文件将在被 RAG 系统处理之前
# 使用增强转换转换为 PDF
```

## 性能考虑

### 转换速度
- **WeasyPrint**：典型文档约 1-3 秒
- **Pandoc**：典型文档约 3-10 秒
- **大型文档**：时间与内容大致呈线性增长

### 内存使用
- **WeasyPrint**：每次转换约 50-100MB
- **Pandoc**：每次转换约 100-200MB
- **图像**：大图像会显著增加内存使用

### 优化技巧
1. **在嵌入前调整大图像大小**
2. **使用压缩图像**（照片用 JPEG，图形用 PNG）
3. **限制并发转换**以避免内存问题
4. **缓存已转换内容**当多次处理时

## 示例

### 示例 Markdown 文档

```markdown
# 技术文档

## 目录
[TOC]

## 概述
本文档提供全面的技术规范。

## 架构

### 系统组件
1. **解析引擎**：处理文档处理
2. **存储层**：管理数据持久化
3. **查询接口**：提供搜索功能

### 代码实现
```python
from raganything import RAGAnything

# 初始化系统
rag = RAGAnything(config={
    "working_dir": "./storage",
    "enable_image_processing": True
})

# 处理文档
await rag.process_document_complete("document.pdf")
```

### 性能指标

| 组件 | 吞吐量 | 延迟 | 内存 |
|-----------|------------|---------|--------|
| 解析器 | 100 文档/小时 | 平均 36 秒 | 2.5 GB |
| 存储 | 1000 操作/秒 | 平均 1 毫秒 | 512 MB |
| 查询 | 50 查询/秒 | 平均 20 毫秒 | 1 GB |

## 集成说明

> **重要**：在处理前始终验证输入。

## 结论
增强系统为文档处理工作流提供了出色的性能。
```

### 生成的 PDF 功能

增强 Markdown 转换器生成的 PDF 具有：

- **专业排版**，具有适当的字体选择和间距
- **语法高亮的代码块**，使用 Pygments
- **格式化的表格**，带有边框和交替行颜色
- **可点击的目录**，带有导航链接
- **响应式图像**，可适当缩放
- **自定义样式**，通过 CSS
- **适当的分页符**和边距
- **文档元数据**和属性

## 故障排除

### 常见问题

#### WeasyPrint 安装问题
```bash
# Ubuntu/Debian: 安装系统依赖
sudo apt-get update
sudo apt-get install -y build-essential python3-dev libcairo2 \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    libffi-dev shared-mime-info

# 然后重新安装 WeasyPrint
pip install --force-reinstall weasyprint
```

#### 找不到 Pandoc
```bash
# 检查是否安装了 Pandoc
pandoc --version

# 安装 Pandoc (Ubuntu/Debian)
sudo apt-get install pandoc wkhtmltopdf

# 或从此处下载：https://pandoc.org/installing.html
```

#### CSS 问题
- 检查 custom_css 中的 CSS 语法
- 验证 CSS 文件路径是否存在
- 首先使用简单的 HTML 测试 CSS
- 使用浏览器开发者工具调试样式

#### 图像问题
- 确保图像可访问（正确的路径）
- 检查图像文件格式（支持 PNG、JPEG、GIF）
- 验证图像文件权限
- 考虑图像大小和格式优化

#### 字体问题
```python
# 使用网页安全字体
config = MarkdownConfig(
    custom_css="""
    body {
        font-family: 'Arial', 'Helvetica', sans-serif;
    }
    """
)
```

### 调试模式

启用详细日志以进行故障排除：

```python
import logging

# 启用调试日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 创建带有调试日志的转换器
converter = EnhancedMarkdownConverter()
result = converter.convert_file_to_pdf("test.md", "test.pdf")
```

### 错误处理

```python
def robust_conversion(input_path, output_path):
    """使用回退后端进行转换"""
    converter = EnhancedMarkdownConverter()

    # 按优先顺序尝试后端
    backends = ["weasyprint", "pandoc", "auto"]

    for backend in backends:
        try:
            success = converter.convert_file_to_pdf(
                input_path=input_path,
                output_path=output_path,
                method=backend
            )
            if success:
                print(f"✅ 使用 {backend} 转换成功")
                return True
        except Exception as e:
            print(f"❌ {backend} 失败: {str(e)}")
            continue

    print("❌ 所有后端都失败了")
    return False
```

## API 参考

### EnhancedMarkdownConverter

```python
class EnhancedMarkdownConverter:
    def __init__(self, config: Optional[MarkdownConfig] = None):
        """使用可选配置初始化转换器"""

    def convert_file_to_pdf(self, input_path: str, output_path: str, method: str = "auto") -> bool:
        """将 Markdown 文件转换为 PDF"""

    def convert_markdown_to_pdf(self, markdown_content: str, output_path: str, method: str = "auto") -> bool:
        """将 Markdown 内容转换为 PDF"""

    def get_backend_info(self) -> Dict[str, Any]:
        """获取有关可用后端的信息"""

    def convert_with_weasyprint(self, markdown_content: str, output_path: str) -> bool:
        """使用 WeasyPrint 后端转换"""

    def convert_with_pandoc(self, markdown_content: str, output_path: str) -> bool:
        """使用 Pandoc 后端转换"""
```

## 最佳实践

1. **为您的用例选择正确的后端**：
   - **WeasyPrint** 用于网页风格文档和自定义 CSS
   - **Pandoc** 用于学术论文和复杂格式
   - **Auto** 用于通用用途和开发

2. **在嵌入前优化图像**：
   - 使用适当的格式（照片用 JPEG，图形用 PNG）
   - 压缩图像以减小文件大小
   - 设置合理的最大宽度

3. **设计响应式布局**：
   - 使用相对单位（%、em）而不是绝对单位（px）
   - 使用不同的页面大小进行测试
   - 考虑打印特定的 CSS

4. **测试您的样式**：
   - 从默认样式开始并逐步自定义
   - 在生产使用前使用示例内容进行测试
   - 验证 CSS 语法

5. **优雅地处理错误**：
   - 实现回退后端
   - 提供有意义的错误消息
   - 记录转换尝试以进行调试

6. **性能优化**：
   - 可能时缓存已转换内容
   - 使用适当的工作线程数处理大批量
   - 监控大型文档的内存使用

## 结论

增强 Markdown 转换功能提供专业品质的 PDF 生成，具有灵活的样式选项和多后端支持。它与 RAG-Anything 的文档处理管道无缝集成，同时为 Markdown 到 PDF 转换需求提供独立功能。
