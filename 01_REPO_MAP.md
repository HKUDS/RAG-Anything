# 01_REPO_MAP.md — RAG-Anything Repository Structure

## Directory Tree
```
RAG-Anything/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── dependabot.yml
│   ├── pull_request_template.md
│   └── workflows/
│       ├── linting.yaml
│       └── pypi-publish.yml
├── .pre-commit-config.yaml
├── assets/
│   └── (logo, framework images)
├── docs/
│   ├── batch_processing.md
│   ├── context_aware_processing.md
│   ├── enhanced_markdown.md
│   ├── multimodal_rag_failure_modes.md
│   ├── offline_setup.md
│   └── vllm_integration.md
├── examples/
│   ├── batch_dry_run_example.py
│   ├── batch_processing_example.py
│   ├── enhanced_markdown_example.py
│   ├── image_format_test.py
│   ├── insert_content_list_example.py
│   ├── lmstudio_integration_example.py
│   ├── minimax_integration_example.py
│   ├── modalprocessors_example.py
│   ├── office_document_test.py
│   ├── ollama_integration_example.py
│   ├── raganything_example.py
│   ├── text_format_test.py
│   └── vllm_integration_example.py
├── reproduce/
│   ├── index.py
│   ├── llm_answer_evaluator.py
│   └── query.py
├── scripts/
│   └── create_tiktoken_cache.py
├── tests/  (22 test files)
│   ├── test_asset_urls.py
│   ├── test_callbacks.py
│   ├── test_chinese_cid_font.py
│   ├── test_close_event_loop.py
│   ├── test_content_list_alias_handling.py
│   ├── test_core_modules.py
│   ├── test_custom_parser.py
│   ├── test_doc_status_creation.py
│   ├── test_embedding_examples.py
│   ├── test_full_entities_merge.py
│   ├── test_insert_content_list.py
│   ├── test_minimax_integration.py
│   ├── test_omml_extractor.py
│   ├── test_parser_url_download.py
│   ├── test_processor_lightrag_api.py
│   ├── test_prompt_language.py
│   ├── test_raganything_example.py
│   ├── test_resilience.py
│   ├── test_strip_thinking_tags.py
│   ├── testpaddleocr_parser.py
│   ├── testparser_kwargs.py
│   └── testparser_wiring.py
├── raganything/  (main source — 19 modules)
│   ├── __init__.py           — Package init, exports
│   ├── asset_urls.py         — Asset URL handling
│   ├── base.py               — Base class
│   ├── batch.py              — Batch processing logic
│   ├── batch_parser.py       — Batch parser
│   ├── callbacks.py          — Callback system
│   ├── config.py             — Configuration
│   ├── enhanced_markdown.py  — Markdown enhancement
│   ├── modalprocessors.py    — Modal content processors (60KB)
│   ├── omml_extractor.py     — OMML extraction
│   ├── parser.py             — Main parser (102KB)
│   ├── processor.py          — Main processor (91KB)
│   ├── prompt.py             — English prompts
│   ├── prompt_manager.py     — Prompt management
│   ├── prompts_zh.py         — Chinese prompts
│   ├── query.py              — Query handling (32KB)
│   ├── raganything.py        — Main class (27KB)
│   ├── resilience.py         — Resilience/retry logic (14KB)
│   └── utils.py              — Utilities (12KB)
├── .gitignore
├── .pre-commit-config.yaml
├── LICENSE
├── MANIFEST.in
├── README.md
├── README_zh.md
├── env.example
├── pyproject.toml
├── requirements.txt
└── setup.py
```

## Core Source Modules (raganything/)

### Entry Point
- **`raganything.py`** — `RAGAnything` main class; orchestrates document ingestion, parsing, multimodal processing, and indexing into LightRAG

### Processing Pipeline
- **`processor.py`** — `Processor` class; handles chunking, content separation, template application, multimodal content processing
- **`parser.py`** — Document parsing; MinerU integration + fallback; handles PDF, Office, images, etc.
- **`batch.py`** — Batch document processing coordinator
- **`batch_parser.py`** — Batch parsing with status tracking

### Modal Processors
- **`modalprocessors.py`** — `ImageModalProcessor`, `TableModalProcessor`, `EquationModalProcessor`, `TextModalProcessor` for multimodal content analysis

### Prompting
- **`prompt.py`** — English prompt templates for vision/LLM analysis
- **`prompts_zh.py`** — Chinese prompt templates
- **`prompt_manager.py`** — Prompt management system

### Query & Retrieval
- **`query.py`** — Query handling, context construction, multimodal retrieval

### Supporting
- **`callbacks.py`** — Callback system for progress tracking
- **`config.py`** — Configuration constants (file extensions, limits)
- **`resilience.py`** — Retry logic, error handling
- **`utils.py`** — Helper functions
- **`enhanced_markdown.py`** — Markdown enhancement
- **`omml_extractor.py`** — Office Math ML extraction
- **`asset_urls.py`** — Asset URL handling
- **`base.py`** — Base class definitions

## Upstream Branches
| Branch | Purpose |
|--------|---------|
| main | Stable branch |
| async | Async features |
| audio | Audio processing |
| cache | Caching features |
| dev | Development |
| omnirag | Omni RAG features |
| ui | UI components |

## Example Scripts
| Script | Purpose |
|--------|---------|
| raganything_example.py | Basic end-to-end usage |
| insert_content_list_example.py | Direct content insertion |
| modalprocessors_example.py | Modal processor demo |
| batch_processing_example.py | Batch document processing |
| enhanced_markdown_example.py | Markdown processing |

## Dependencies Graph
```
raganything/
├── parser.py → uses MinerU (mineru[core])
├── processor.py → uses modalprocessors, prompts, utils
├── raganything.py → uses processor, parser, batch, query
├── batch.py → uses batch_parser
└── modalprocessors.py → uses VLM for image/table/equation analysis
```