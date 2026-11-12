#!/usr/bin/env python3
"""
Image Format Parsing Test Script for RAG-Anything

This script demonstrates how to parse various image formats
using MinerU, including JPG, PNG, BMP, TIFF, GIF, and WebP files.

Requirements:
- PIL/Pillow library for format conversion
- RAG-Anything package

Usage:
    python image_format_test.py --file path/to/image.bmp
"""

import argparse
import asyncio
import sys
from pathlib import Path
from raganything import RAGAnything


def check_pillow_installation():
    """Check if PIL/Pillow is installed and available"""
    try:
        from PIL import Image

        print(
            f"✅ PIL/Pillow found: PIL version {Image.__version__ if hasattr(Image, '__version__') else 'Unknown'}"
        )
        return True
    except ImportError:
        print("❌ PIL/Pillow not found. Please install Pillow:")
        print("  pip install Pillow")
        return False


def get_image_info(image_path: Path):
    """Get detailed image information"""
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            return {
                "format": img.format,
                "mode": img.mode,
                "size": img.size,
                "has_transparency": img.mode in ("RGBA", "LA")
                or "transparency" in img.info,
            }
    except Exception as e:
        return {"error": str(e)}


async def test_image_format_parsing(file_path: str):
    """Test image format parsing with MinerU"""

    print(f"🧪 Testing image format parsing: {file_path}")

    # Check if file exists and is a supported image format
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"❌ File does not exist: {file_path}")
        return False

    supported_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tiff",
        ".tif",
        ".gif",
        ".webp",
    }
    if file_path.suffix.lower() not in supported_extensions:
        print(f"❌ Unsupported file format: {file_path.suffix}")
        print(f"   Supported formats: {', '.join(supported_extensions)}")
        return False

    print(f"📸 File format: {file_path.suffix.upper()}")
    print(f"📏 File size: {file_path.stat().st_size / 1024:.1f} KB")

    # Get detailed image information
    img_info = get_image_info(file_path)
    if "error" not in img_info:
        print("🖼️  Image info:")
        print(f"   • Format: {img_info['format']}")
        print(f"   • Mode: {img_info['mode']}")
        print(f"   • Size: {img_info['size'][0]}x{img_info['size'][1]}")
        print(f"   • Has transparency: {img_info['has_transparency']}")

    # Check format compatibility with MinerU
    mineru_native_formats = {".jpg", ".jpeg", ".png"}
    needs_conversion = file_path.suffix.lower() not in mineru_native_formats

    if needs_conversion:
        print(
            f"ℹ️  Format {file_path.suffix.upper()} will be converted to PNG for MinerU compatibility"
        )
    else:
        print(f"✅ Format {file_path.suffix.upper()} is natively supported by MinerU")

    # Initialize RAGAnything (only for parsing functionality)
    rag = RAGAnything()

    try:
        # Test image parsing with MinerU
        print("\n🔄 Testing image parsing with MinerU...")
        content_list, doc_id = await rag.parse_document(
            file_path=str(file_path),
            output_dir="./test_output",
            parse_method="ocr",  # Images use OCR method
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
            print("\n📄 No text extracted from the image")

        # Display image processing results
        image_items = [
            item
            for item in content_list
            if isinstance(item, dict) and item.get("type") == "image"
        ]
        if image_items:
            print(f"\n🖼️  Found {len(image_items)} processed image(s):")
            for i, item in enumerate(image_items, 1):
                print(f"   {i}. Image path: {item.get('img_path', 'N/A')}")
                caption = item.get("image_caption", item.get("img_caption", []))
                if caption:
                    print(f"      Caption: {caption[0] if caption else 'N/A'}")

        # Display text blocks (OCR results)
        text_items = [
            item
            for item in content_list
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if text_items:
            print("\n📝 OCR text blocks found:")
            for i, item in enumerate(text_items, 1):
                text_content = item.get("text", "")
                if text_content.strip():
                    preview = text_content.strip()[:200]
                    print(
                        f"   {i}. {preview}{'...' if len(text_content) > 200 else ''}"
                    )

        # Check for any tables detected in the image
        table_items = [
            item
            for item in content_list
            if isinstance(item, dict) and item.get("type") == "table"
        ]
        if table_items:
            print(f"\n📊 Found {len(table_items)} table(s) in image:")
            for i, item in enumerate(table_items, 1):
                print(f"   {i}. Table detected with content")

        print("\n🎉 Image format parsing test completed successfully!")
        print("📁 Output files saved to: ./test_output")
        return True

    except Exception as e:
        print(f"\n❌ Image format parsing failed: {str(e)}")
        import traceback

        print(f"   Full error: {traceback.format_exc()}")
        return False


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Test image format parsing with MinerU"
    )
    parser.add_argument("--file", help="Path to the image file to test")
    parser.add_argument(
        "--check-pillow", action="store_true", help="Only check PIL/Pillow installation"
    )

    args = parser.parse_args()

    # Check PIL/Pillow installation
    print("🔧 Checking PIL/Pillow installation...")
    if not check_pillow_installation():
        return 1

    if args.check_pillow:
        print("✅ PIL/Pillow installation check passed!")
        return 0

    # If not just checking dependencies, file argument is required
    if not args.file:
        print("❌ Error: --file argument is required when not using --check-pillow")
        parser.print_help()
        return 1

    # Run the parsing test
    try:
        success = asyncio.run(test_image_format_parsing(args.file))
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n⏹️ Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
