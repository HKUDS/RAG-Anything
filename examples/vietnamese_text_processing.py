#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vietnamese Text Processing Example for RAG-Anything
Ví dụ xử lý tài liệu Text tiếng Việt với RAG-Anything

Tập trung vào xử lý các định dạng:
- TXT: File văn bản thuần túy
- MD: File Markdown
- DOCX: File Word
- PDF: File PDF chứa text

Không xử lý: Image, Audio, Video, Table phức tạp, Equation
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

from raganything import RAGAnything, RAGAnythingConfig
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc


async def main():
    """Main function để xử lý tài liệu tiếng Việt"""

    # Load environment variables từ .env.vietnamese
    env_file = Path(__file__).parent.parent / ".env.vietnamese"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"✅ Đã load config từ: {env_file}")
    else:
        print(f"⚠️  Không tìm thấy {env_file}, sử dụng config mặc định")

    # Lấy API configuration
    api_key = os.getenv("OPENAI_API_KEY", "your-api-key")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    if api_key == "your-api-key" or api_key == "your_openai_api_key_here":
        print("\n❌ Lỗi: Vui lòng cập nhật OPENAI_API_KEY trong file .env.vietnamese")
        print("Chỉnh sửa file .env.vietnamese và thay thế 'your_openai_api_key_here' bằng API key của bạn\n")
        return

    # Tạo RAGAnything configuration - TẮT multimodal processing
    config = RAGAnythingConfig(
        working_dir=os.getenv("WORKING_DIR", "./rag_storage_vietnamese"),
        parser=os.getenv("PARSER", "mineru"),
        parse_method=os.getenv("PARSE_METHOD", "auto"),
        parser_output_dir=os.getenv("OUTPUT_DIR", "./output_vietnamese"),

        # TẮT tất cả tính năng multimodal - CHỈ XỬ LÝ TEXT
        enable_image_processing=False,
        enable_table_processing=False,
        enable_equation_processing=False,

        # Context extraction cho tiếng Việt
        context_window=2,
        max_context_tokens=3000,

        display_content_stats=True,
    )

    print("\n" + "="*60)
    print("🇻🇳 RAG-Anything - Vietnamese Text Processing")
    print("="*60)
    print(f"📁 Working directory: {config.working_dir}")
    print(f"📄 Parser: {config.parser}")
    print(f"🔧 Parse method: {config.parse_method}")
    print(f"🖼️  Image processing: {config.enable_image_processing}")
    print(f"📊 Table processing: {config.enable_table_processing}")
    print(f"🧮 Equation processing: {config.enable_equation_processing}")
    print("="*60 + "\n")

    # Define LLM model function
    def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        return openai_complete_if_cache(
            "gpt-4o-mini",
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    # Define embedding function
    embedding_func = EmbeddingFunc(
        embedding_dim=3072,
        max_token_size=8192,
        func=lambda texts: openai_embed(
            texts,
            model="text-embedding-3-large",
            api_key=api_key,
            base_url=base_url,
        ),
    )

    # Initialize RAGAnything
    print("⚙️  Đang khởi tạo RAGAnything...")
    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
        # Không cần vision_model_func vì đã tắt image processing
    )
    print("✅ Khởi tạo RAGAnything thành công!\n")

    # Ví dụ 1: Xử lý một file văn bản tiếng Việt
    print("📝 Ví dụ 1: Xử lý file văn bản tiếng Việt")
    print("-" * 60)

    # Tạo một file test nếu chưa có
    test_file = Path("./test_data/vietnamese_sample.txt")
    test_file.parent.mkdir(exist_ok=True)

    if not test_file.exists():
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("""Trí tuệ nhân tạo và RAG (Retrieval-Augmented Generation)

RAG là một kiến trúc mới trong lĩnh vực xử lý ngôn ngữ tự nhiên, kết hợp khả năng tìm kiếm thông tin với khả năng sinh văn bản của các mô hình ngôn ngữ lớn.

Ưu điểm của RAG:
1. Cải thiện độ chính xác của thông tin
2. Giảm thiểu hiện tượng "hallucination" của LLM
3. Cho phép cập nhật kiến thức mà không cần train lại mô hình
4. Tăng tính minh bạch và khả năng truy xuất nguồn gốc thông tin

Các thành phần chính:
- Document Parser: Phân tích và trích xuất nội dung từ tài liệu
- Embedding Model: Chuyển đổi văn bản thành vector
- Vector Database: Lưu trữ và tìm kiếm vector
- LLM: Sinh câu trả lời dựa trên context được truy xuất

Ứng dụng trong tiếng Việt:
RAG đặc biệt hữu ích cho xử lý tài liệu tiếng Việt, giúp trả lời câu hỏi dựa trên kho tài liệu nội bộ, hỗ trợ nghiên cứu, và xây dựng chatbot chuyên ngành.
""")
        print(f"✅ Đã tạo file test: {test_file}")

    # Xử lý file
    try:
        print(f"\n📄 Đang xử lý file: {test_file}")
        await rag.process_document_complete(
            file_path=str(test_file),
            output_dir=config.parser_output_dir,
            parse_method="txt",
            display_stats=True,
        )
        print("✅ Xử lý file thành công!\n")
    except Exception as e:
        print(f"❌ Lỗi khi xử lý file: {e}\n")
        return

    # Ví dụ 2: Truy vấn thông tin bằng tiếng Việt
    print("\n🔍 Ví dụ 2: Truy vấn thông tin bằng tiếng Việt")
    print("-" * 60)

    queries = [
        "RAG là gì?",
        "Ưu điểm của RAG là gì?",
        "RAG có những thành phần chính nào?",
        "Làm thế nào để áp dụng RAG cho tiếng Việt?",
    ]

    for query in queries:
        print(f"\n❓ Câu hỏi: {query}")
        try:
            result = await rag.aquery(query, mode="hybrid")
            print(f"💬 Trả lời: {result}\n")
            print("-" * 60)
        except Exception as e:
            print(f"❌ Lỗi khi truy vấn: {e}\n")

    # Ví dụ 3: Xử lý folder chứa nhiều file
    print("\n📂 Ví dụ 3: Xử lý folder chứa nhiều file tiếng Việt")
    print("-" * 60)
    print(f"Để xử lý folder, sử dụng:")
    print(f"""
    await rag.process_folder_complete(
        folder_path="./your_vietnamese_documents",
        output_dir="{config.parser_output_dir}",
        file_extensions=[".txt", ".md", ".docx", ".pdf"],
        recursive=True,
        max_workers=2
    )
    """)

    print("\n" + "="*60)
    print("✅ Hoàn thành demo xử lý tài liệu tiếng Việt!")
    print("="*60 + "\n")


if __name__ == "__main__":
    print("\n🚀 Bắt đầu xử lý tài liệu Text tiếng Việt với RAG-Anything\n")
    asyncio.run(main())
