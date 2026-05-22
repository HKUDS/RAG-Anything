# 05_PR_CANDIDATES.md — RAG-Anything Open PR & Issue Analysis

## Open Pull Requests (5)

| # | Title | Author | Labels | Priority |
|---|-------|--------|--------|----------|
| #283 | fix: improve MinerU image-text mapping with section and neighbor context | Eleven-Mouse | — | HIGH |
| #281 | feat: add VideoModalProcessor with visual + audio dual-channel analysis | liuruing | — | HIGH |
| #280 | feat: add AudioModalProcessor for speech-to-text transcription | liuruing | — | HIGH |
| #270 | feat: add RAG-Anything Studio — standalone multimodal-aware Web UI | devinlovekoala | — | MEDIUM |
| #190 | Feat: Released FastAPI Service for RAG-Anything | LaansDole | — | MEDIUM |

## High-Impact Open Issues (by label)

### Bug Reports (bug)
| # | Title | Author | Notes |
|---|-------|--------|-------|
| #167 | [Bug]: run LightRAG/examples/raganything_example.py — `hashing_kv` errors in multimodal | zkailinzhang | Multiple `hashing_kv` errors; embedding dimension mismatch (3072 vs 1024) |
| #126 | mineru.cli.client numpy.core.multiarray import error | Thinking80s | NumPy compatibility issue |
| #119 | `DocProcessingStatus.__init__()` unexpected `multimodal_processed` kwarg | gptbert | Regression |
| #112 | mineru verification error | c200312 | MinerU config check |
| #107 | mineru extras require conflicting PyTorch versions | AbdelkarimAZZAZ | Dependency conflict |
| #95 | UnboundLocalError: `first_stage_tasks` | Kumneger49 | Async task handling |
| #91 | `DocProcessingStatus.__init__()` multimodal_processed kwarg (duplicate) | frngo001 | Regression |
| #89 | mineru2.0: img_caption → image_caption | Justin-12138 | Field rename |
| #184 | ASCII codec can't encode character '\u2018' | ahmedwaqar | Encoding issue |

### Feature Requests (enhancement)
| # | Title | Author | Notes |
|---|-------|--------|-------|
| #156 | Incremental folder scan by date and md5 | ghost | High demand, saves processing time |
| #154 | Enable cache data insertion for new graph database | Jarod-Leo | Switching DBs loses cache |
| #150 | Provide container image for testing | Bodanel | Docker deployment |
| #133 | Support Remote MinerU instance | voycey | Remote MinerU server |
| #130 | Multi-modal embedding model support | BukeLy | Custom embedding models |
| #178 | PaddleOCR available for parser | shkim4u | OCR parser option |
| #213 | Structured RAG failure-mode checklist (WFGY 16-problem map) | onestardao | Documentation |
| #200 | (empty title) | ayushmittalde | — |
| #224 | (empty title) | vega-he | — |

### Questions (question)
| # | Title | Author | Notes |
|---|-------|--------|-------|
| #276 | raganything with lightrag api server? | Nevermetyou65 | API server integration |
| #271 | Image Retrieval Issue (related to #283) | aleenavarghese29 | MinerU image-text mapping |
| #146 | Local model support (ollama, huggingface) | wangquanyue1994 | Local LLM support |
| #149 | Return images during retrieval? | UncleFB | Image retrieval in RAG |
| #164 | VLM re-processes documents every run (KG not persisted?) | a-rookie-create | KG persistence |
| #173 | How to retrieval multimodal content path | hexmSeeU | Image path retrieval |
| #143 | raganything_example.py no Reranker config | HZWHH | Reranker missing |
| #136 | Chinese data retrieves English content | Typhoona | Language mismatch |
| #131 | License question: MIT vs AGPL (MinerU) | paperworksllc | Legal/compliance |
| #108 | Ollama models timeout via LiteLLM-Proxy | mikumiiku | Ollama integration |

## PR #283 Analysis (MinerU Image-Text Mapping Fix)
- **Status**: Open, very recent (today)
- **Tests**: 242 passed, 1 skipped
- **Related Issues**: #271 (Image Retrieval Issue)
- **Files changed**: utils.py, modalprocessors.py, processor.py, prompt.py
- **Assessment**: Well-documented, test-covered, targets a real bug in image retrieval

## PR #280/#281 Analysis (Audio/Video Processors)
- **Status**: #280 is prerequisite for #281
- **Both**: Open today, well-structured
- **Assessment**: Major new modality support (audio, video) — significant feature additions

## PR #270 Analysis (RAG-Anything Studio Web UI)
- **Status**: Open
- **Assessment**: Standalone Web UI for multimodal-aware interactions

## PR #190 Analysis (FastAPI Service)
- **Status**: Open since Jan 2026, has contributor association
- **Assessment**: FastAPI wrapper for RAG-Anything, may need rebase

## Quality Concerns Found
1. Several test files import non-existent classes (`PaddleOCRParser`, `DoclingParser`)
2. `test_strip_thinking_tags.py` appears incomplete (empty test functions)
3. `testpaddleocr_parser.py` fails at import
4. `testparser_kwargs.py` fails at import (DoclingParser missing)
5. `test_custom_parser.py`, `test_embedding_examples.py` fail at import
6. Integration tests fail due to missing LightRAG mock (NoneType on doc_status)