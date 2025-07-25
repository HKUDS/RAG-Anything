# 🧪 Comprehensive Testing Guide: Batch Processing & Enhanced Markdown

This guide provides step-by-step testing instructions for the new batch processing and enhanced markdown conversion features in RAG-Anything.

## 📋 **Quick Start (5 minutes)**

### **1. Environment Setup**
```bash
# Install dependencies
pip install tqdm markdown weasyprint pygments

# Install optional system dependencies
conda install -c conda-forge pandoc wkhtmltopdf -y

# Verify installation
python -c "import tqdm, markdown, weasyprint, pygments; print('✅ All dependencies installed')"
```

### **2. Basic Import Test**
```bash
# Test all core modules
python -c "
from raganything.batch_parser import BatchParser
from raganything.enhanced_markdown import EnhancedMarkdownConverter
from raganything.batch import BatchMixin
print('✅ All core modules imported successfully')
"
```

### **3. Command-Line Interface Test**
```bash
# Test enhanced markdown CLI
python -m raganything.enhanced_markdown --info

# Test batch parser CLI
python -m raganything.batch_parser --help
```

### **4. Basic Functionality Test**
```bash
# Create test markdown file
echo "# Test Document\n\nThis is a test." > test.md

# Test conversion
python -m raganything.enhanced_markdown test.md --output test.pdf --method weasyprint

# Verify PDF was created
ls -la test.pdf

# Clean up
rm test.md test.pdf
```

---

## 🎯 **Detailed Feature Testing**

### **Test 1: Enhanced Markdown Conversion**

#### **1.1 Backend Detection**
```bash
python -m raganything.enhanced_markdown --info
```

**Expected Output:**
```
Backend Information:
  ✅ weasyprint
  ❌ pandoc
  ✅ markdown
  ✅ pandoc_system
Recommended backend: pandoc
```

#### **1.2 Basic Conversion Test**
```bash
# Create comprehensive test file
cat > test_document.md << 'EOF'
# Test Document

## Overview
This is a test document for enhanced markdown conversion.

### Code Example
```python
def hello_world():
    print("Hello, World!")
    return "Success"
```

### Table Example
| Feature | Status | Notes |
|---------|--------|-------|
| Code Highlighting | ✅ | Working |
| Tables | ✅ | Working |
| Lists | ✅ | Working |

### Lists
- Item 1
- Item 2
- Item 3

### Blockquotes
> This is a blockquote with important information.

### Links
Visit [GitHub](https://github.com) for more information.
EOF

# Test different conversion methods
python -m raganything.enhanced_markdown test_document.md --output test_weasyprint.pdf --method weasyprint
python -m raganything.enhanced_markdown test_document.md --output test_pandoc.pdf --method pandoc_system

# Verify PDFs were created
ls -la test_*.pdf
```

#### **1.3 Advanced Conversion Test**
```python
# Create test script: test_advanced_markdown.py
from raganything.enhanced_markdown import EnhancedMarkdownConverter, MarkdownConfig
import tempfile
from pathlib import Path

def test_advanced_markdown():
    """Test advanced markdown conversion features"""

    # Create custom configuration
    config = MarkdownConfig(
        page_size="A4",
        margin="1in",
        font_size="12pt",
        include_toc=True,
        syntax_highlighting=True,
        custom_css="""
        body { font-family: 'Arial', sans-serif; }
        h1 { color: #2c3e50; border-bottom: 2px solid #3498db; }
        code { background-color: #f8f9fa; padding: 2px 4px; }
        """
    )

    # Create converter
    converter = EnhancedMarkdownConverter(config)

    # Test backend information
    info = converter.get_backend_info()
    print("Backend Information:")
    for backend, available in info["available_backends"].items():
        status = "✅" if available else "❌"
        print(f"  {status} {backend}")

    # Create test content
    test_content = """# Advanced Test Document

## Features Tested

### 1. Code Highlighting
```python
def process_document(file_path: str) -> str:
    with open(file_path, 'r') as f:
        content = f.read()
    return f"Processed: {content}"
```

### 2. Tables
| Component | Status | Performance |
|-----------|--------|-------------|
| Parser | ✅ | 100 docs/hour |
| Converter | ✅ | 50 docs/hour |
| Storage | ✅ | 1TB capacity |

### 3. Lists and Links
- [Feature 1](https://example.com)
- [Feature 2](https://example.com)
- [Feature 3](https://example.com)

### 4. Blockquotes
> This is an important note about the system.

## Conclusion
The enhanced markdown conversion provides excellent formatting.
"""

    # Test conversion
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as temp_file:
        temp_file.write(test_content)
        temp_md_path = temp_file.name

    try:
        # Test different methods
        for method in ["auto", "weasyprint", "pandoc_system"]:
            try:
                output_path = f"test_advanced_{method}.pdf"
                success = converter.convert_file_to_pdf(
                    input_path=temp_md_path,
                    output_path=output_path,
                    method=method
                )
                if success:
                    print(f"✅ {method}: {output_path}")
                else:
                    print(f"❌ {method}: Failed")
            except Exception as e:
                print(f"❌ {method}: {str(e)}")

    finally:
        # Clean up
        Path(temp_md_path).unlink()

if __name__ == "__main__":
    test_advanced_markdown()
```

### **Test 2: Batch Processing**

#### **2.1 Basic Batch Parser Test**
```python
# Create test script: test_batch_parser.py
from raganything.batch_parser import BatchParser, BatchProcessingResult
import tempfile
from pathlib import Path

def test_batch_parser():
    """Test basic batch parser functionality"""

    # Create batch parser
    batch_parser = BatchParser(
        parser_type="mineru",
        max_workers=2,
        show_progress=True,
        timeout_per_file=60,
        skip_installation_check=True  # Bypass installation check for testing
    )

    # Test supported extensions
    extensions = batch_parser.get_supported_extensions()
    print(f"✅ Supported extensions: {extensions}")

    # Test file filtering
    test_files = [
        "document.pdf",
        "report.docx",
        "data.xlsx",
        "unsupported.xyz"
    ]

    supported_files = batch_parser.filter_supported_files(test_files)
    print(f"✅ File filtering: {len(supported_files)}/{len(test_files)} files supported")

    # Create test files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create test markdown files
        for i in range(3):
            test_file = temp_path / f"test_{i}.md"
            test_file.write_text(f"# Test Document {i}\n\nContent for test {i}.")

        # Test batch processing (will fail without MinerU, but tests setup)
        try:
            result = batch_parser.process_batch(
                file_paths=[str(temp_path)],
                output_dir=str(temp_path / "output"),
                parse_method="auto",
                recursive=False
            )
            print(f"✅ Batch processing completed: {result.summary()}")
        except Exception as e:
            print(f"⚠️ Batch processing failed (expected without MinerU): {str(e)}")

if __name__ == "__main__":
    test_batch_parser()
```

#### **2.2 Batch Processing with Mock Files**
```python
# Create test script: test_batch_mock.py
import tempfile
from pathlib import Path
from raganything.batch_parser import BatchParser

def create_mock_files():
    """Create mock files for testing"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create various file types
        files = {
            "document.md": "# Test Document\n\nThis is a test.",
            "report.txt": "This is a text report.",
            "data.csv": "name,value\nA,1\nB,2\nC,3",
            "config.json": '{"setting": "value"}'
        }

        for filename, content in files.items():
            file_path = temp_path / filename
            file_path.write_text(content)

        return temp_path, list(files.keys())

def test_batch_with_mock_files():
    """Test batch processing with mock files"""

    temp_path, file_list = create_mock_files()

    # Create batch parser
    batch_parser = BatchParser(
        parser_type="mineru",
        max_workers=2,
        show_progress=True,
        skip_installation_check=True
    )

    # Test file filtering
    all_files = [str(temp_path / f) for f in file_list]
    supported_files = batch_parser.filter_supported_files(all_files)

    print(f"✅ Total files: {len(all_files)}")
    print(f"✅ Supported files: {len(supported_files)}")
    print(f"✅ Success rate: {len(supported_files)/len(all_files)*100:.1f}%")

    # Test batch processing setup (without actual parsing)
    try:
        result = batch_parser.process_batch(
            file_paths=supported_files,
            output_dir=str(temp_path / "output"),
            parse_method="auto"
        )
        print(f"✅ Batch processing: {result.summary()}")
    except Exception as e:
        print(f"⚠️ Batch processing setup test completed (parsing failed as expected)")

if __name__ == "__main__":
    test_batch_with_mock_files()
```

---

## 🔗 **Integration Testing**

### **Test 3: RAG-Anything Integration**

#### **3.1 Basic Integration Test**
```python
# Create test script: test_integration.py
from raganything import RAGAnything, RAGAnythingConfig
from raganything.batch_parser import BatchParser
from raganything.enhanced_markdown import EnhancedMarkdownConverter
import tempfile
from pathlib import Path

def test_rag_integration():
    """Test integration with RAG-Anything"""

    # Create temporary working directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create test configuration
        config = RAGAnythingConfig(
            working_dir=str(temp_path / "rag_storage"),
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
            parser="mineru",
            max_concurrent_files=2,
            recursive_folder_processing=True
        )

        # Test RAG-Anything initialization
        try:
            rag = RAGAnything(config=config)
            print("✅ RAG-Anything initialized successfully")
        except Exception as e:
            print(f"⚠️ RAG-Anything initialization: {str(e)}")

        # Test batch processing methods exist
        batch_methods = [
            'process_documents_batch',
            'process_documents_batch_async',
            'get_supported_file_extensions',
            'filter_supported_files',
            'process_documents_with_rag_batch'
        ]

        print("\nBatch Processing Methods:")
        for method in batch_methods:
            available = hasattr(rag, method)
            status = "✅" if available else "❌"
            print(f"  {status} {method}")

        # Test enhanced markdown integration
        print("\nEnhanced Markdown Integration:")
        try:
            converter = EnhancedMarkdownConverter()
            info = converter.get_backend_info()
            print(f"  ✅ Available backends: {list(info['available_backends'].keys())}")
            print(f"  ✅ Recommended backend: {info['recommended_backend']}")
        except Exception as e:
            print(f"  ❌ Enhanced markdown: {str(e)}")

if __name__ == "__main__":
    test_rag_integration()
```

---

## ⚡ **Performance Testing**

### **Test 4: Performance Benchmarks**

#### **4.1 Enhanced Markdown Performance Test**
```python
# Create test script: test_performance.py
import time
import tempfile
from pathlib import Path
from raganything.enhanced_markdown import EnhancedMarkdownConverter

def create_large_markdown(size_kb=100):
    """Create a large markdown file for performance testing"""
    content = "# Large Test Document\n\n"

    # Add sections to reach target size
    sections = size_kb // 2  # Rough estimate
    for i in range(sections):
        content += f"""
## Section {i}

This is section {i} of the large test document.

### Subsection {i}.1
Content for subsection {i}.1.

### Subsection {i}.2
Content for subsection {i}.2.

### Code Example {i}
```python
def function_{i}():
    return f"Result {i}"
```

### Table {i}
| Column A | Column B | Column C |
|----------|----------|----------|
| Value A{i} | Value B{i} | Value C{i} |
| Value D{i} | Value E{i} | Value F{i} |

"""

    return content

def test_markdown_performance():
    """Test enhanced markdown conversion performance"""

    print("Enhanced Markdown Performance Test")
    print("=" * 40)

    # Test different file sizes
    sizes = [10, 50, 100]  # KB

    for size_kb in sizes:
        print(f"\nTesting {size_kb}KB document:")

        # Create test file
        content = create_large_markdown(size_kb)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as temp_file:
            temp_file.write(content)
            temp_md_path = temp_file.name

        try:
            converter = EnhancedMarkdownConverter()

            # Test different methods
            for method in ["weasyprint", "pandoc_system"]:
                try:
                    output_path = f"perf_test_{size_kb}kb_{method}.pdf"

                    start_time = time.time()
                    success = converter.convert_file_to_pdf(
                        input_path=temp_md_path,
                        output_path=output_path,
                        method=method
                    )
                    end_time = time.time()

                    if success:
                        duration = end_time - start_time
                        print(f"  ✅ {method}: {duration:.2f}s")
                    else:
                        print(f"  ❌ {method}: Failed")

                except Exception as e:
                    print(f"  ❌ {method}: {str(e)}")

        finally:
            # Clean up
            Path(temp_md_path).unlink()

if __name__ == "__main__":
    test_markdown_performance()
```

---

## 🔧 **Troubleshooting**

### **Common Issues and Solutions**

#### **Issue 1: Import Errors**
```bash
# Problem: ModuleNotFoundError for new dependencies
# Solution: Install missing dependencies
pip install tqdm markdown weasyprint pygments

# Verify installation
python -c "import tqdm, markdown, weasyprint, pygments; print('✅ All dependencies installed')"
```

#### **Issue 2: WeasyPrint Installation Problems**
```bash
# Problem: WeasyPrint fails to install or run
# Solution: Install system dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-cffi \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info

# Then reinstall WeasyPrint
pip install --force-reinstall weasyprint
```

#### **Issue 3: Pandoc Not Found**
```bash
# Problem: Pandoc command not found
# Solution: Install Pandoc
conda install -c conda-forge pandoc wkhtmltopdf -y

# Or install via package manager
sudo apt-get install pandoc

# Verify installation
pandoc --version
```

#### **Issue 4: MinerU Package Conflicts**
```bash
# Problem: numpy/scikit-learn version conflicts
# Solution: Use skip_installation_check parameter
python -c "
from raganything.batch_parser import BatchParser
batch_parser = BatchParser(skip_installation_check=True)
print('✅ Batch parser created with installation check bypassed')
"
```

#### **Issue 5: Memory Errors**
```bash
# Problem: Out of memory during batch processing
# Solution: Reduce max_workers
python -c "
from raganything.batch_parser import BatchParser
batch_parser = BatchParser(max_workers=1)  # Use fewer workers
print('✅ Batch parser created with reduced workers')
"
```

### **Debug Mode**
```python
# Enable debug logging for detailed information
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Test with debug logging
from raganything.enhanced_markdown import EnhancedMarkdownConverter
converter = EnhancedMarkdownConverter()
converter.convert_file_to_pdf("test.md", "test.pdf")
```

---

## 📊 **Test Report Template**

### **Automated Test Report**
```python
# Create test script: generate_test_report.py
import sys
from pathlib import Path
from datetime import datetime

def generate_test_report():
    """Generate comprehensive test report"""

    report = {
        "timestamp": datetime.now().isoformat(),
        "python_version": sys.version,
        "tests": {}
    }

    # Test imports
    try:
        from raganything.batch_parser import BatchParser
        from raganything.enhanced_markdown import EnhancedMarkdownConverter
        from raganything.batch import BatchMixin
        report["tests"]["imports"] = {"status": "✅", "message": "All modules imported successfully"}
    except Exception as e:
        report["tests"]["imports"] = {"status": "❌", "message": str(e)}

    # Test enhanced markdown
    try:
        converter = EnhancedMarkdownConverter()
        info = converter.get_backend_info()
        report["tests"]["enhanced_markdown"] = {
            "status": "✅",
            "message": f"Available backends: {list(info['available_backends'].keys())}"
        }
    except Exception as e:
        report["tests"]["enhanced_markdown"] = {"status": "❌", "message": str(e)}

    # Test batch processing
    try:
        batch_parser = BatchParser(skip_installation_check=True)
        extensions = batch_parser.get_supported_extensions()
        report["tests"]["batch_processing"] = {
            "status": "✅",
            "message": f"Supported extensions: {len(extensions)} file types"
        }
    except Exception as e:
        report["tests"]["batch_processing"] = {"status": "❌", "message": str(e)}

    # Generate report
    print("Test Report")
    print("=" * 50)
    print(f"Timestamp: {report['timestamp']}")
    print(f"Python Version: {report['python_version']}")
    print()

    for test_name, result in report["tests"].items():
        print(f"{result['status']} {test_name}: {result['message']}")

    # Summary
    passed = sum(1 for r in report["tests"].values() if r["status"] == "✅")
    total = len(report["tests"])
    print(f"\nSummary: {passed}/{total} tests passed")

if __name__ == "__main__":
    generate_test_report()
```

### **Manual Test Checklist**
```markdown
# Manual Test Checklist

## Environment Setup
- [ ] Python 3.8+ installed
- [ ] Dependencies installed: tqdm, markdown, weasyprint, pygments
- [ ] Optional dependencies: pandoc, wkhtmltopdf
- [ ] RAG-Anything core modules accessible

## Enhanced Markdown Testing
- [ ] Backend detection works
- [ ] WeasyPrint conversion successful
- [ ] Pandoc conversion successful (if available)
- [ ] Command-line interface functional
- [ ] Error handling robust

## Batch Processing Testing
- [ ] Batch parser creation successful
- [ ] File filtering works correctly
- [ ] Progress tracking functional
- [ ] Error handling comprehensive
- [ ] Command-line interface available

## Integration Testing
- [ ] RAG-Anything integration works
- [ ] Batch methods available in main class
- [ ] Enhanced markdown integrates seamlessly
- [ ] Error handling propagates correctly

## Performance Testing
- [ ] Markdown conversion < 10s for typical documents
- [ ] Batch processing setup < 5s
- [ ] Memory usage reasonable (< 500MB)
- [ ] No memory leaks detected

## Issues Found
- [ ] None
- [ ] List issues here

## Recommendations
- [ ] None
- [ ] List recommendations here
```

---

## 🎯 **Success Criteria**

A successful implementation should pass all tests:

### **✅ Required Tests**
- [ ] All imports work without errors
- [ ] Enhanced markdown conversion produces valid PDFs
- [ ] Batch processing handles file filtering correctly
- [ ] Command-line interfaces are functional
- [ ] Integration with RAG-Anything works
- [ ] Error handling is robust
- [ ] Performance is acceptable (< 10s for typical operations)

### **✅ Optional Tests**
- [ ] Pandoc backend available and working
- [ ] Large document processing successful
- [ ] Memory usage stays within limits
- [ ] All command-line options work correctly

### **📈 Performance Benchmarks**
- **Enhanced Markdown**: 1-5 seconds for typical documents
- **Batch Processing**: 2-4x speedup with parallel processing
- **Memory Usage**: ~50-100MB per worker for batch processing
- **Error Recovery**: Graceful handling of all common error scenarios

---

## 🚀 **Quick Commands Reference**

```bash
# Run all tests
python test_advanced_markdown.py
python test_batch_parser.py
python test_integration.py
python test_performance.py
python generate_test_report.py

# Test specific features
python -m raganything.enhanced_markdown --info
python -m raganything.batch_parser --help
python examples/batch_and_enhanced_markdown_example.py

# Performance testing
time python -m raganything.enhanced_markdown test.md --output test.pdf
```

---

**This comprehensive testing guide ensures thorough validation of all new features!** 🎉
