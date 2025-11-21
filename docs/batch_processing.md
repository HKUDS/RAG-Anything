# 批量处理

本文档描述了 RAG-Anything 的批量处理功能，该功能允许您并行处理多个文档以提高吞吐量。

## 概述

批量处理功能允许您并发处理多个文档，显著提高大型文档集合的吞吐量。它提供了并行处理、进度跟踪、错误处理和灵活的配置选项。

## 主要特性

- **并行处理**：使用线程池并发处理多个文件
- **进度跟踪**：使用 `tqdm` 实现实时进度条
- **错误处理**：全面的错误报告和恢复机制
- **灵活输入**：支持文件、目录和递归搜索
- **可配置工作线程**：可调整并行工作线程数量
- **安装检查绕过**：针对存在包冲突的环境提供可选跳过功能

## 安装

```bash
# 基础安装
pip install raganything[all]

# 批量处理所需
pip install tqdm
```

## 使用方法

### 基本批量处理

```python
from raganything.batch_parser import BatchParser

# 创建批量解析器
batch_parser = BatchParser(
    parser_type="mineru",  # 或 "docling"
    max_workers=4,
    show_progress=True,
    timeout_per_file=300,
    skip_installation_check=False  # 如果遇到解析器安装问题，设置为 True
)

# 处理多个文件
result = batch_parser.process_batch(
    file_paths=["doc1.pdf", "doc2.docx", "folder/"],
    output_dir="./batch_output",
    parse_method="auto",
    recursive=True
)

# 检查结果
print(result.summary())
print(f"成功率: {result.success_rate:.1f}%")
print(f"处理时间: {result.processing_time:.2f} 秒")
```

### 异步批量处理

```python
import asyncio
from raganything.batch_parser import BatchParser

async def async_batch_processing():
    batch_parser = BatchParser(
        parser_type="mineru",
        max_workers=4,
        show_progress=True
    )

    # 异步处理文件
    result = await batch_parser.process_batch_async(
        file_paths=["doc1.pdf", "doc2.docx"],
        output_dir="./output",
        parse_method="auto"
    )

    return result

# 运行异步处理
result = asyncio.run(async_batch_processing())
```

### 与 RAG-Anything 集成

```python
from raganything import RAGAnything

rag = RAGAnything()

# 使用批量功能处理文档
result = rag.process_documents_batch(
    file_paths=["doc1.pdf", "doc2.docx"],
    output_dir="./output",
    max_workers=4,
    show_progress=True
)

print(f"成功处理 {len(result.successful_files)} 个文件")
```

### 处理文档并集成 RAG

```python
# 批量处理文档，然后将它们添加到 RAG
result = await rag.process_documents_with_rag_batch(
    file_paths=["doc1.pdf", "doc2.docx"],
    output_dir="./output",
    max_workers=4,
    show_progress=True
)

print(f"使用 RAG 处理了 {result['successful_rag_files']} 个文件")
print(f"总处理时间: {result['total_processing_time']:.2f} 秒")
```

### 命令行界面

```bash
# 基本批量处理
python -m raganything.batch_parser path/to/docs/ --output ./output --workers 4

# 使用特定解析器
python -m raganything.batch_parser path/to/docs/ --parser mineru --method auto

# 不显示进度条
python -m raganything.batch_parser path/to/docs/ --output ./output --no-progress

# 帮助
python -m raganything.batch_parser --help
```

## 配置

### 环境变量

```env
# 批量处理配置
MAX_CONCURRENT_FILES=4
SUPPORTED_FILE_EXTENSIONS=.pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.txt,.md
RECURSIVE_FOLDER_PROCESSING=true
PARSER_OUTPUT_DIR=./parsed_output
```

### BatchParser 参数

- **parser_type**：`"mineru"` 或 `"docling"`（默认：`"mineru"`）
- **max_workers**：并行工作线程数（默认：`4`）
- **show_progress**：显示进度条（默认：`True`）
- **timeout_per_file**：每个文件的超时时间（秒）（默认：`300`）
- **skip_installation_check**：跳过解析器安装检查（默认：`False`）

## 支持的文件类型

- **PDF 文件**：`.pdf`
- **Office 文档**：`.doc`、`.docx`、`.ppt`、`.pptx`、`.xls`、`.xlsx`
- **图像**：`.png`、`.jpg`、`.jpeg`、`.bmp`、`.tiff`、`.tif`、`.gif`、`.webp`
- **文本文件**：`.txt`、`.md`

## API 参考

### BatchProcessingResult

```python
@dataclass
class BatchProcessingResult:
    successful_files: List[str]      # 成功处理的文件
    failed_files: List[str]          # 失败的文件
    total_files: int                 # 文件总数
    processing_time: float           # 总处理时间（秒）
    errors: Dict[str, str]           # 失败文件的错误消息
    output_dir: str                  # 使用的输出目录

    def summary(self) -> str:        # 人类可读的摘要
    def success_rate(self) -> float: # 成功率百分比
```

### BatchParser 方法

```python
class BatchParser:
    def __init__(self, parser_type: str = "mineru", max_workers: int = 4, ...):
        """初始化批量解析器"""

    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名列表"""

    def filter_supported_files(self, file_paths: List[str], recursive: bool = True) -> List[str]:
        """过滤文件，仅保留支持的类型"""

    def process_batch(self, file_paths: List[str], output_dir: str, ...) -> BatchProcessingResult:
        """批量处理文件"""

    async def process_batch_async(self, file_paths: List[str], output_dir: str, ...) -> BatchProcessingResult:
        """异步批量处理文件"""
```

## 性能考虑

### 内存使用
- 每个工作线程使用额外内存
- 建议：大多数系统使用 2-4 个工作线程
- 处理大文件时监控内存使用情况

### CPU 使用
- 并行处理利用多核心
- 最佳工作线程数取决于 CPU 核心数和文件大小
- 处理大量小文件时 I/O 可能成为瓶颈

### 推荐设置
- **小文件**（< 1MB）：较高的工作线程数（6-8）
- **大文件**（> 100MB）：较低的工作线程数（2-3）
- **混合大小**：从 4 个工作线程开始并调整

## 故障排除

### 常见问题

#### 内存错误
```python
# 解决方案：减少 max_workers
batch_parser = BatchParser(max_workers=2)
```

#### 超时错误
```python
# 解决方案：增加 timeout_per_file
batch_parser = BatchParser(timeout_per_file=600)  # 10 分钟
```

#### 解析器安装问题
```python
# 解决方案：跳过安装检查
batch_parser = BatchParser(skip_installation_check=True)
```

#### 文件未找到错误
- 检查文件路径和权限
- 确保输入文件存在
- 验证目录访问权限

### 调试模式

启用调试日志以获取详细信息：

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 创建带有调试日志的批量解析器
batch_parser = BatchParser(parser_type="mineru", max_workers=2)
```

### 错误处理

批量处理器提供全面的错误处理：

```python
result = batch_parser.process_batch(file_paths=["doc1.pdf", "doc2.docx"])

# 检查错误
if result.failed_files:
    print("失败的文件:")
    for file_path in result.failed_files:
        error_message = result.errors.get(file_path, "未知错误")
        print(f"  - {file_path}: {error_message}")

# 仅处理成功的文件
for file_path in result.successful_files:
    print(f"成功处理: {file_path}")
```

## 示例

### 处理整个目录

```python
from pathlib import Path

# 处理目录中所有支持的文件
batch_parser = BatchParser(max_workers=4)
directory_path = Path("./documents")

result = batch_parser.process_batch(
    file_paths=[str(directory_path)],
    output_dir="./processed",
    recursive=True  # 包含子目录
)

print(f"处理了 {len(result.successful_files)} 个文件，共 {result.total_files} 个")
```

### 处理前过滤文件

```python
# 获取目录中的所有文件
all_files = ["doc1.pdf", "image.png", "spreadsheet.xlsx", "unsupported.xyz"]

# 仅过滤支持的文件
supported_files = batch_parser.filter_supported_files(all_files)
print(f"将处理 {len(supported_files)} 个文件，共 {len(all_files)} 个")

# 仅处理支持的文件
result = batch_parser.process_batch(
    file_paths=supported_files,
    output_dir="./output"
)
```

### 自定义错误处理

```python
def process_with_retry(file_paths, max_retries=3):
    """使用重试逻辑处理文件"""

    for attempt in range(max_retries):
        result = batch_parser.process_batch(file_paths, "./output")

        if not result.failed_files:
            break  # 所有文件处理成功

        print(f"尝试 {attempt + 1}: {len(result.failed_files)} 个文件失败")
        file_paths = result.failed_files  # 重试失败的文件

    return result
```

## 最佳实践

1. **从默认设置开始**，根据性能进行调整
2. **监控系统资源**在批量处理期间
3. **使用适合您硬件的工作线程数**
4. **优雅地处理错误**，使用重试逻辑
5. **先用小批量测试**，然后再处理大型集合
6. **使用 skip_installation_check** 如果遇到解析器安装问题
7. **启用进度跟踪**用于长时间运行的操作
8. **设置适当的超时**基于预期的文件处理时间

## 结论

批量处理功能显著提高了 RAG-Anything 处理大型文档集合的吞吐量。它提供了灵活的配置选项、全面的错误处理，并与现有的 RAG-Anything 管道无缝集成。
