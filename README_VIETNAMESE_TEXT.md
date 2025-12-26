# 🇻🇳 RAG-Anything - Phiên bản tối ưu cho Text tiếng Việt

> **Vietnamese Text Processing Optimized Version**
>
> Phiên bản này được tối ưu hóa để xử lý các tài liệu **TEXT tiếng Việt** như `.txt`, `.md`, `.docx`, `.pdf` (text-based).
>
> Đã **TẮT** các tính năng xử lý multimodal không cần thiết (image, table, equation) để tập trung vào xử lý text hiệu quả.

---

## 📋 Mục lục

- [Giới thiệu](#-giới-thiệu)
- [Tính năng](#-tính-năng)
- [Cài đặt](#-cài-đặt)
- [Cấu hình](#-cấu-hình)
- [Sử dụng](#-sử-dụng)
- [Ví dụ](#-ví-dụ)
- [FAQ](#-faq)

---

## 🌟 Giới thiệu

**RAG-Anything Vietnamese Text** là phiên bản tối ưu hóa của [RAG-Anything](https://github.com/HKUDS/RAG-Anything) được cấu hình đặc biệt để xử lý **tài liệu văn bản tiếng Việt**.

### Điểm khác biệt:

✅ **Tập trung vào TEXT**:
- Chỉ xử lý các định dạng văn bản: TXT, MD, DOCX, PDF (text-only)
- Loại bỏ xử lý hình ảnh, bảng biểu phức tạp, công thức toán học
- Giảm thiểu dependencies và resource usage

✅ **Tối ưu cho tiếng Việt**:
- Hỗ trợ encoding UTF-8 đầy đủ
- Xử lý tốt dấu tiếng Việt
- Context window được điều chỉnh cho văn bản tiếng Việt

✅ **Hiệu suất cao**:
- Xử lý nhanh hơn do không cần VLM (Vision Language Model)
- Tiết kiệm API calls và chi phí
- Phù hợp cho xử lý batch documents lớn

---

## 🎯 Tính năng

### Định dạng hỗ trợ

| Định dạng | Mô tả | Trạng thái |
|-----------|-------|------------|
| 📝 `.txt` | File văn bản thuần túy | ✅ Hỗ trợ đầy đủ |
| 📄 `.md` | File Markdown | ✅ Hỗ trợ đầy đủ |
| 📘 `.docx` | Microsoft Word | ✅ Hỗ trợ (cần LibreOffice) |
| 📕 `.pdf` | PDF văn bản | ✅ Hỗ trợ |

### Tính năng đã TẮT (để tối ưu cho text)

| Tính năng | Trạng thái | Lý do |
|-----------|------------|-------|
| 🖼️ Image Processing | ❌ TẮT | Không cần cho text |
| 📊 Table Processing | ❌ TẮT | Tối ưu cho text thuần |
| 🧮 Equation Processing | ❌ TẮT | Không cần cho text |

---

## 📦 Cài đặt

### 1. Clone repository

```bash
git clone https://github.com/HKUDS/RAG-Anything.git
cd RAG-Anything
```

### 2. Cài đặt dependencies

```bash
# Cài đặt basic dependencies
pip install -e .

# Hoặc cài đặt với text support
pip install -e ".[text]"
```

### 3. Cài đặt LibreOffice (cho DOCX)

**Chỉ cần nếu bạn muốn xử lý file .docx**

- **Ubuntu/Debian**: `sudo apt-get install libreoffice`
- **macOS**: `brew install --cask libreoffice`
- **Windows**: Tải từ [libreoffice.org](https://www.libreoffice.org/download/download/)

---

## ⚙️ Cấu hình

### File cấu hình: `.env.vietnamese`

File này đã được tạo sẵn với cấu hình tối ưu cho text tiếng Việt:

```bash
# API Configuration
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1

# Working Directory
WORKING_DIR=./rag_storage_vietnamese
OUTPUT_DIR=./output_vietnamese

# Parser Configuration
PARSER=mineru
PARSE_METHOD=auto

# Multimodal Processing - TẮT các tính năng không cần
ENABLE_IMAGE_PROCESSING=False
ENABLE_TABLE_PROCESSING=False
ENABLE_EQUATION_PROCESSING=False

# Text Processing
SUPPORTED_FILE_EXTENSIONS=.txt,.md,.docx,.pdf

# Context Extraction cho tiếng Việt
CONTEXT_WINDOW=2
MAX_CONTEXT_TOKENS=3000
```

### Cập nhật API Key

**QUAN TRỌNG**: Chỉnh sửa file `.env.vietnamese` và thay thế:

```bash
OPENAI_API_KEY=your_openai_api_key_here
```

bằng API key thực của bạn.

---

## 🚀 Sử dụng

### Script demo có sẵn

Chúng tôi đã chuẩn bị sẵn script demo: `examples/vietnamese_text_processing.py`

```bash
# Chạy demo
python examples/vietnamese_text_processing.py
```

### Sử dụng trong code Python

```python
import asyncio
from raganything import RAGAnything, RAGAnythingConfig
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc

async def process_vietnamese_text():
    # Cấu hình cho text tiếng Việt
    config = RAGAnythingConfig(
        working_dir="./rag_storage_vietnamese",
        parser="mineru",
        parse_method="auto",

        # TẮT multimodal - CHỈ XỬ LÝ TEXT
        enable_image_processing=False,
        enable_table_processing=False,
        enable_equation_processing=False,

        # Context cho tiếng Việt
        context_window=2,
        max_context_tokens=3000,
    )

    # Khởi tạo RAG
    rag = RAGAnything(
        config=config,
        llm_model_func=your_llm_function,
        embedding_func=your_embedding_function,
    )

    # Xử lý file tiếng Việt
    await rag.process_document_complete(
        file_path="tai_lieu_tieng_viet.txt",
        output_dir="./output_vietnamese",
    )

    # Truy vấn bằng tiếng Việt
    result = await rag.aquery(
        "Nội dung chính của tài liệu là gì?",
        mode="hybrid"
    )
    print(result)

# Chạy
asyncio.run(process_vietnamese_text())
```

---

## 📚 Ví dụ

### Ví dụ 1: Xử lý file TXT tiếng Việt

```python
# Tạo file test
with open("test_vietnamese.txt", "w", encoding="utf-8") as f:
    f.write("""
    Trí tuệ nhân tạo (AI) đang thay đổi thế giới.
    RAG giúp cải thiện độ chính xác của chatbot.
    Công nghệ này rất hữu ích cho doanh nghiệp Việt Nam.
    """)

# Xử lý file
await rag.process_document_complete(
    file_path="test_vietnamese.txt",
    parse_method="txt",
)

# Hỏi đáp
result = await rag.aquery("AI đang làm gì?", mode="hybrid")
```

### Ví dụ 2: Xử lý folder chứa nhiều file

```python
await rag.process_folder_complete(
    folder_path="./tai_lieu_cong_ty",
    output_dir="./output_vietnamese",
    file_extensions=[".txt", ".md", ".docx"],
    recursive=True,
    max_workers=2,
)
```

### Ví dụ 3: Truy vấn với nhiều câu hỏi

```python
questions = [
    "Tài liệu nói về chủ đề gì?",
    "Các điểm chính là gì?",
    "Có những khuyến nghị nào?",
]

for question in questions:
    answer = await rag.aquery(question, mode="hybrid")
    print(f"Q: {question}")
    print(f"A: {answer}\n")
```

---

## ❓ FAQ

### Q1: Tại sao tắt Image/Table/Equation processing?

**A:** Để tối ưu hóa cho text:
- Giảm dependencies phức tạp
- Không cần Vision Language Model (tiết kiệm cost)
- Xử lý nhanh hơn
- Phù hợp với 90% use case xử lý văn bản

### Q2: Có thể bật lại các tính năng multimodal không?

**A:** Có! Chỉnh sửa `.env.vietnamese`:

```bash
ENABLE_IMAGE_PROCESSING=True
ENABLE_TABLE_PROCESSING=True
ENABLE_EQUATION_PROCESSING=True
```

Và cung cấp `vision_model_func` khi khởi tạo RAGAnything.

### Q3: File DOCX có cần LibreOffice không?

**A:** Có, để convert DOCX sang PDF trước khi parse. Nếu không cài LibreOffice, bạn có thể:
- Convert DOCX sang TXT/PDF trước
- Chỉ xử lý TXT, MD, PDF

### Q4: Xử lý tiếng Việt có khác gì?

**A:** Hệ thống tự động xử lý:
- UTF-8 encoding
- Dấu tiếng Việt
- Context window được điều chỉnh

Bạn không cần config đặc biệt.

### Q5: Chi phí API sử dụng như thế nào?

**A:** Phiên bản text-only này tiết kiệm hơn nhiều:
- Không cần GPT-4V (vision model)
- Chỉ dùng GPT-4o-mini cho text
- Embedding: text-embedding-3-large

Ước tính: ~$0.01 - $0.05 per document (tùy độ dài)

### Q6: Có thể dùng model local không?

**A:** Có! Thay thế OpenAI bằng:
- Ollama
- LM Studio
- Groq
- Anthropic Claude

Xem `examples/lmstudio_integration_example.py`

---

## 🔗 Liên kết hữu ích

- [RAG-Anything Repository](https://github.com/HKUDS/RAG-Anything)
- [LightRAG](https://github.com/HKUDS/LightRAG)
- [MinerU Parser](https://github.com/opendatalab/MinerU)

---

## 📝 License

MIT License - Xem file [LICENSE](LICENSE)

---

## 💬 Hỗ trợ

Nếu bạn gặp vấn đề hoặc có câu hỏi:

1. Kiểm tra [Issues](https://github.com/HKUDS/RAG-Anything/issues)
2. Tạo issue mới với tag `vietnamese` hoặc `text-processing`
3. Join [Discord Community](https://discord.gg/yF2MmDJyGJ)

---

<div align="center">

**🇻🇳 Made with ❤️ for Vietnamese Text Processing**

Phiên bản này được tối ưu hóa đặc biệt cho cộng đồng developer Việt Nam

[⭐ Star trên GitHub](https://github.com/HKUDS/RAG-Anything) | [📖 Documentation](https://github.com/HKUDS/RAG-Anything/blob/main/README.md) | [💬 Community](https://discord.gg/yF2MmDJyGJ)

</div>
