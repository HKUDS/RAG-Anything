#!/usr/bin/env python3
"""
Text Format Parsing Test Script for RAG-Anything

This script demonstrates how to parse various text formats
using MinerU, including TXT and MD files.

Requirements:
- ReportLab library for PDF conversion
- RAG-Anything package

Usage:
    python text_format_test.py --file path/to/text/document.md
"""

import argparse
import asyncio
import sys
from pathlib import Path
from raganything import RAGAnything


def check_reportlab_installation():
    """Check if ReportLab is installed and available"""
    try:
        import reportlab

        print(
            f"✅ ReportLab found: version {reportlab.Version if hasattr(reportlab, 'Version') else 'Unknown'}"
        )
        return True
    except ImportError:
        print("❌ ReportLab not found. Please install ReportLab:")
        print("  pip install reportlab")
        return False


async def test_text_format_parsing(file_path: str):
    """Test text format parsing with MinerU"""

    print(f"🧪 Testing text format parsing: {file_path}")

    # Check if file exists and is a supported text format
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"❌ File does not exist: {file_path}")
        return False

    supported_extensions = {".txt", ".md"}
    if file_path.suffix.lower() not in supported_extensions:
        print(f"❌ Unsupported file format: {file_path.suffix}")
        print(f"   Supported formats: {', '.join(supported_extensions)}")
        return False

    print(f"📄 File format: {file_path.suffix.upper()}")
    print(f"📏 File size: {file_path.stat().st_size / 1024:.1f} KB")

    # Display text file info
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        print(f"📝 Text length: {len(content)} characters")
        print(f"📋 Line count: {len(content.splitlines())}")
    except UnicodeDecodeError:
        print(
            "⚠️  Text encoding: Non-UTF-8 (will try multiple encodings during processing)"
        )

    # Initialize RAGAnything (only for parsing functionality)
    rag = RAGAnything()

    try:
        # Test text parsing with MinerU
        print("\n🔄 Testing text parsing with MinerU...")
        content_list, doc_id = await rag.parse_document(
            file_path=str(file_path),
            output_dir="./test_output",
            parse_method="auto",
            display_stats=True,
        )

        extracted_text = "\n\n".join(
            item.get("text", "")
            for item in content_list
            if isinstance(item, dict)
            and item.get("type") == "text"
            and item.get("text", "").strip()
        )

        print("✅ Parsing successful!")
        print(f"   🆔 Document ID: {doc_id}")
        print(f"   📊 Content blocks: {len(content_list)}")
        print(f"   📝 Extracted text length: {len(extracted_text)} characters")

        # Analyze content types
        content_types = {}
        for item in content_list:
            if isinstance(item, dict):
                content_type = item.get("type", "unknown")
                content_types[content_type] = content_types.get(content_type, 0) + 1

        if content_types:
            print("   📋 Content distribution:")
            for content_type, count in sorted(content_types.items()):
                print(f"      • {content_type}: {count}")

        # Display extracted text (if any)
        if extracted_text.strip():
            print("\n📄 Extracted text preview (first 500 characters):")
            preview = extracted_text.strip()[:500]
            print(f"   {preview}{'...' if len(extracted_text) > 500 else ''}")
        else:
            print("\n📄 No text extracted from the document")

        # Display text blocks
        text_items = [
            item
            for item in content_list
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if text_items:
            print("\n📝 Text blocks found:")
            for i, item in enumerate(text_items[:3], 1):
                text_content = item.get("text", "")
                if text_content.strip():
                    preview = text_content.strip()[:200]
                    print(
                        f"   {i}. {preview}{'...' if len(text_content) > 200 else ''}"
                    )

        # Check for any tables detected in the text
        table_items = [
            item
            for item in content_list
            if isinstance(item, dict) and item.get("type") == "table"
        ]
        if table_items:
            print(f"\n📊 Found {len(table_items)} table(s) in document:")
            for i, item in enumerate(table_items, 1):
                table_body = item.get("table_body", "")
                row_count = len(table_body.split("\n"))
                print(f"   {i}. Table with {row_count} rows")

        # Check for images (unlikely in text files but possible in MD)
        image_items = [
            item
            for item in content_list
            if isinstance(item, dict) and item.get("type") == "image"
        ]
        if image_items:
            print(f"\n🖼️  Found {len(image_items)} image(s):")
            for i, item in enumerate(image_items, 1):
                print(f"   {i}. Image path: {item.get('img_path', 'N/A')}")

        print("\n🎉 Text format parsing test completed successfully!")
        print("📁 Output files saved to: ./test_output")
        return True

    except Exception as e:
        print(f"\n❌ Text format parsing failed: {str(e)}")
        import traceback

        print(f"   Full error: {traceback.format_exc()}")
        return False


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Test text format parsing with MinerU")
    parser.add_argument("--file", help="Path to the text file to test")
    parser.add_argument(
        "--check-reportlab",
        action="store_true",
        help="Only check ReportLab installation",
    )

    args = parser.parse_args()

    # Check ReportLab installation
    print("🔧 Checking ReportLab installation...")
    if not check_reportlab_installation():
        return 1

    if args.check_reportlab:
        print("✅ ReportLab installation check passed!")
        return 0

    # If not just checking dependencies, file argument is required
    if not args.file:
        print("❌ Error: --file argument is required when not using --check-reportlab")
        parser.print_help()
        return 1

    # Run the parsing test
    try:
        success = asyncio.run(test_text_format_parsing(args.file))
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n⏹️ Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
