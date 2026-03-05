# RAG-Anything FastAPI Service

**Simple Upload → Process → Q&A Pipeline** for Office documents and Excel files. Optimized for structured text processing without image/vision overhead.

## Quick Start

Using uv:
```bash
# Install dependencies
uv add fastapi 'uvicorn[standard]'

# Start the server
uv run uvicorn api.app:app --reload
```

Server will be available at: http://127.0.0.1:8000/docs

## Environment Variables

Configure via `.env` file (see project root `.env.example` for details):
```env
# Support for any OpenAI-compatible backend (LM Studio, Ollama, vLLM, DeepSeek, etc.)
LLM_BINDING_HOST=http://localhost:1234/v1
LLM_BINDING_API_KEY=lm-studio
# Recommended: Use models with 262k+ context (e.g., Qwen) to avoid overflow
LLM_MODEL=openai/gpt-oss-20b
EMBEDDING_BINDING_HOST=http://localhost:1234/v1
EMBEDDING_BINDING_API_KEY=lm-studio
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_DIM=768 # Ensure this matches your model (e.g. 1024 for bge-m3)
WORKING_DIR=./rag_storage_service
```

## Simple API Endpoints

### Core Pipeline
- `GET /health` - Health check
- `POST /process-file` - Upload Office documents (DOC, DOCX, PDF, etc.)
- `POST /process-excel` - Upload Excel files (XLS, XLSX)
- `POST /query` - Ask questions about processed documents

### Advanced Querying
- `POST /query-multimodal` - Query with structured content (tables, text)

## Usage Workflow

1. **Upload & Process**: Upload your document using `/process-file` or `/process-excel`
2. **Query**: Ask questions using `/query`

## Excel Processing Features

- Automatic conversion to natural language text
- Dataset summaries and column statistics
- Configurable row limits and chunk sizes
- Support for multiple sheets
- Direct RAG system integration

## Example Usage

```bash
# 1. Upload Excel file
curl -X POST "http://localhost:8000/process-excel" \
  -F "file=@data.xlsx" \
  -F "max_rows=500"

# 2. Query the data
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the main patterns in this data?"}'
```

**Note:** Vision/image processing has been removed to focus on Office document workflows.
