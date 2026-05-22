# API Reference

This document provides a complete API reference for RAG-Anything.

## Installation

```bash
pip install raganything
```

## Core Classes

### RAGAnything

The main class for multimodal document processing and RAG operations.

```python
from raganything import RAGAnything, RAGAnythingConfig
```

#### Initialization

```python
rag = RAGAnything(
    lightrag=None,                    # Optional pre-initialized LightRAG instance
    llm_model_func=None,              # LLM model function for text analysis
    vision_model_func=None,           # Vision model function for image analysis  
    embedding_func=None,             # Embedding function for text vectorization
    config=None,                      # RAGAnythingConfig object (default: from env)
    lightrag_kwargs={},              # Additional LightRAG init arguments
)
```

#### Methods

##### `ingest(path, **kwargs)`

Ingest a document or directory of documents.

```python
result = rag.ingest(
    path="path/to/document.pdf",     # File or directory path
    file_format=None,                # Force specific format (auto-detected if None)
    **kwargs                        # Additional parser-specific kwargs
)
```

Returns a dictionary with:
- `texts`: List of extracted text chunks
- `images`: List of extracted image data
- `tables`: List of extracted tables
- `equations`: List of extracted equations

##### `query(question, mode="hybrid", **kwargs)`

Query the RAG system with a question.

```python
result = rag.query(
    question="What is the main topic?",  # Query string
    mode="hybrid",                         # "local", "global", "hybrid", "mix"
    **kwargs                              # Additional query parameters
)
```

Returns a dictionary with retrieved context and generated answer.

##### `ingest_batch(file_paths, **kwargs)`

Batch ingest multiple files.

```python
result = rag.ingest_batch(
    file_paths=["doc1.pdf", "doc2.docx", "folder/"],
    max_workers=4,                     # Number of parallel workers
    show_progress=True,               # Show progress bars
    timeout_per_file=300,             # Timeout per file in seconds
    skip_installation_check=False,    # Skip parser installation check
    **kwargs
)
```

##### `close()`

Clean up resources.

```python
rag.close()
```

#### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `lightrag` | `LightRAG` | LightRAG instance |
| `config` | `RAGAnythingConfig` | Configuration object |
| `doc_parser` | `Parser` | Document parser |
| `modal_processors` | `Dict` | Multimodal processors |
| `callback_manager` | `CallbackManager` | Processing callbacks |

---

### RAGAnythingConfig

Configuration dataclass for RAGAnything.

```python
from raganything import RAGAnythingConfig

config = RAGAnythingConfig(
    working_dir="./rag_storage",           # RAG storage directory
    parse_method="auto",                    # "auto", "ocr", or "txt"
    parser="mineru",                        # "mineru", "docling", "paddleocr"
    parser_output_dir="./output",           # Parser output directory
    display_content_stats=True,             # Show content statistics
    enable_image_processing=True,           # Enable image processing
    enable_table_processing=True,           # Enable table processing
    enable_equation_processing=True,         # Enable equation processing
    max_concurrent_files=1,                 # Max parallel files
    supported_file_extensions=[...],        # Supported file types
    recursive_folder_processing=True,       # Recursive folder processing
    context_window=1,                       # Context pages before/after
    context_mode="page",                    # "page" or "chunk"
    max_context_tokens=2000,               # Max context tokens
    include_headers=True,                  # Include headers in context
    include_captions=True,                 # Include captions in context
)
```

#### Environment Variables

RAGAnythingConfig reads from environment variables with these defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKING_DIR` | `./rag_storage` | Working directory |
| `PARSE_METHOD` | `auto` | Default parse method |
| `OUTPUT_DIR` | `./output` | Output directory |
| `PARSER` | `mineru` | Default parser |
| `ENABLE_IMAGE_PROCESSING` | `True` | Enable images |
| `ENABLE_TABLE_PROCESSING` | `True` | Enable tables |
| `ENABLE_EQUATION_PROCESSING` | `True` | Enable equations |
| `MAX_CONCURRENT_FILES` | `1` | Max concurrent files |

---

## Parser API

### Parser

```python
from raganything import Parser
```

#### Methods

##### `parse(path, **kwargs)`

Parse a document and return structured content.

```python
result = Parser().parse(
    path="document.pdf",
    parse_method="auto",      # "auto", "ocr", or "txt"
    **kwargs
)
```

##### `parse_batch(file_paths, **kwargs)`

Parse multiple documents in batch.

---

## Optional Modules

### Callbacks

Processing callbacks for observability and metrics.

```python
from raganything import (
    ProcessingCallback,
    MetricsCallback, 
    CallbackManager,
    ProcessingEvent,
)
```

#### ProcessingEvent

Enum representing processing stages:

```python
class ProcessingEvent(Enum):
    PARSE_START = "parse_start"
    PARSE_COMPLETE = "parse_complete"
    INSERT_START = "insert_start"
    INSERT_COMPLETE = "insert_complete"
    ERROR = "error"
```

#### CallbackManager

```python
manager = CallbackManager()

@manager.register(ProcessingEvent.PARSE_START)
def on_parse_start(file_path):
    print(f"Starting to parse: {file_path}")

@manager.register(ProcessingEvent.PARSE_COMPLETE) 
def on_parse_complete(file_path, result):
    print(f"Completed: {file_path}")
```

---

### Prompt Manager

Multilingual prompt management.

```python
from raganything import (
    set_prompt_language,
    get_prompt_language,
    reset_prompts,
    register_prompt_language,
    get_available_languages,
)
```

#### Functions

```python
# Set language (e.g., "en", "zh")
set_prompt_language("zh")

# Get current language
lang = get_prompt_language()  # Returns: "zh"

# Reset to defaults
reset_prompts()

# Register custom language
register_prompt_language("fr", custom_prompts_dict)

# List available languages
languages = get_available_languages()
```

---

### Resilience

Retry decorators and circuit breaker pattern.

```python
from raganything import (
    retry,
    async_retry,
    CircuitBreaker,
)
```

#### `@retry`

Retry decorator for functions.

```python
@retry(max_attempts=3, delay=1.0, exceptions=(ConnectionError,))
def unstable_function():
    # May raise ConnectionError
    ...
```

#### `@async_retry`

Async version of retry decorator.

```python
@async_retry(max_attempts=3, delay=1.0)
async def async_unstable_function():
    ...
```

#### CircuitBreaker

Prevents repeated calls to failing services.

```python
breaker = CircuitBreaker(
    failure_threshold=5,      # Failures before opening
    recovery_timeout=60,     # Seconds before trying again
    expected_exceptions=(ConnectionError,)
)

result = breaker.call(service_function)
```

---

### Version

```python
from raganything import get_version

version = get_version()  # Returns: "1.3.1"
```

---

## Examples

### Basic Usage

```python
from raganything import RAGAnything

# Initialize
rag = RAGAnything(
    llm_model_func=your_llm_func,
    embedding_func=your_embedding_func,
)

# Ingest documents
rag.ingest("path/to/documents/")

# Query
result = rag.query("What is this document about?")
print(result["answer"])

# Cleanup
rag.close()
```

### With Custom Configuration

```python
from raganything import RAGAnything, RAGAnythingConfig

config = RAGAnythingConfig(
    working_dir="./my_rag_storage",
    parser="docling",
    enable_image_processing=True,
    max_concurrent_files=4,
)

rag = RAGAnything(config=config, llm_model_func=llm_func)
```

### Batch Processing

```python
from raganything import RAGAnything

rag = RAGAnything(llm_model_func=llm_func)

# Process multiple files
result = rag.ingest_batch(
    file_paths=["doc1.pdf", "doc2.pdf", "folder/"],
    max_workers=4,
    show_progress=True
)

rag.close()
```