# 00_STATE.md — RAG-Anything Repository State

## Repository Identity
- **Original Repo**: HKUDS/RAG-Anything (HKUDS organization)
- **My Fork**: okwn/RAG-Anything
- **License**: MIT
- **Archived**: No
- **Python**: >=3.10 (pyproject.toml), >=3.9 (setup.py)
- **Homepage**: http://arxiv.org/abs/2510.12323

## Metrics (Live)
| Metric | Value |
|--------|-------|
| Stars | 20,516 |
| Forks | 2,370 |
| Open Issues | 102 |
| Open PRs | ~20+ (observed in search) |
| Watchers | 20,516 |
| Default Branch | main |
| Created | 2025-06-06 |

## Topics
- multi-modal-rag
- retrieval-augmented-generation

## Dependencies
### Core
- `lightrag-hku`
- `mineru[core]`
- `huggingface_hub`
- `tqdm`

### Optional Extras
- `[image]`: Pillow>=10.0.0
- `[text]`: reportlab>=4.0.0
- `[office]`: requires LibreOffice (external)
- `[paddleocr]`: paddleocr>=2.7.0, pypdfium2>=4.25.0
- `[markdown]`: markdown>=3.4.0, weasyprint>=60.0, pygments>=2.10.0
- `[all]`: all optional deps

## CI/CD
- **linting.yaml**: Runs pre-commit on push/PR to main
- **pypi-publish.yml**: Publishes to PyPI on release

## Branch Structure (upstream)
- `main` — stable branch
- `async`, `audio`, `cache`, `dev`, `omnirag`, `ui` — feature branches

## Key Architecture
- Multimodal RAG framework for PDF, Office docs, images, tables, equations
- Built on LightRAG for knowledge graph and retrieval
- MinerU-based parsing with fallback to direct content injection

## Test Suite
- 22 test files in `tests/`
- pytest configuration in pyproject.toml
- Tests cover: core modules, callbacks, parsers, resilience, embedding, etc.

## Current Status
- Fork created at: okwn/RAG-Anything
- Local clone: /root/oss-pr-campaign/repos/rag-anything
- Upstream remote: https://github.com/HKUDS/RAG-Anything.git