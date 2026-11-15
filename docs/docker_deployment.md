# Docker Deployment Guide for RAG-Anything

This document outlines instructions and production operational practices for deploying RAG-Anything using Docker and Docker Compose.

---

## 1. Architectural Highlights

- **Multi-Stage Build**: Separates compile-time tooling (`build-essential`, `git`) from the minimal runtime environment (`python:3.11-slim-bookworm`), minimizing image attack surface and download size.
- **Security Compliance**: Executes under an unprivileged user (`appuser:10001`) with deterministic ownership and restrictive permissions.
- **System Dependencies**: Pre-packaged with required native dependencies including `poppler-utils` (PDF processing), `libgl1` and `libglib2.0-0` (OpenCV rendering), `pandoc` (document format conversion), and `tesseract-ocr`.
- **Healthcheck & Observability**: Integrated runtime healthcheck verifying package imports and environment integrity.
- **Storage Isolation**: Dedicated volume mounts for knowledge graphs (`/app/rag_storage`), parsed artifacts (`/app/parser_output`), model caches (`/home/appuser/.cache`), and read-only input documents (`/app/inputs:ro`).

---

## 2. Quickstart with Docker Compose

### Step 1: Clone Repository & Prepare Environment File

```bash
git clone https://github.com/HKUDS/RAG-Anything.git
cd RAG-Anything

# Create environment configuration from template
cp .env.example .env
```

Edit `.env` and set your API keys and model configurations:

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
VISION_MODEL=gpt-4o-mini
```

### Step 2: Build and Start Container

```bash
docker compose build
docker compose up -d
```

### Step 3: Run Document Processing or Query

You can run processing tasks interactively or via batch commands:

```bash
# Execute processing script against an input document
docker compose run --rm raganything python examples/raganything_example.py \
    --input_file /app/inputs/sample.pdf \
    --query "Summarize the key findings"
```

---

## 3. Standalone Docker Usage

If deploying outside of Docker Compose, build and run standard containers:

```bash
# Build Docker image
docker build -t raganything:latest .

# Run with environment variables and persistent volume mounts
docker run -it --rm \
    --env-file .env \
    -v $(pwd)/rag_storage:/app/rag_storage \
    -v $(pwd)/parser_output:/app/parser_output \
    -v $(pwd)/inputs:/app/inputs:ro \
    raganything:latest \
    python examples/raganything_example.py --help
```

---

## 4. GPU Acceleration (CUDA / PyTorch)

For high-throughput OCR and local vision/audio processing (such as MinerU or Whisper models running on GPU), enable NVIDIA Container Toolkit on your Docker host:

```yaml
# Add GPU reservations to docker-compose.yml:
services:
  raganything:
    # ...
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

Or with `docker run`:

```bash
docker run --gpus all --env-file .env ... raganything:latest
```

---

## 5. Storage and Data Management

| Host Path | Container Path | Purpose | Recommended Mode |
|---|---|---|---|
| `./rag_storage` | `/app/rag_storage` | Vector database and LightRAG working state | Read / Write |
| `./parser_output` | `/app/parser_output` | Extracted figures, tables, and intermediate JSON | Read / Write |
| `./inputs` | `/app/inputs` | Source documents (PDF, DOCX, images) | Read-Only (`:ro`) |
| Named Volume `raganything-cache` | `/home/appuser/.cache` | Hugging Face & PyTorch pre-trained model cache | Read / Write |

---

## 6. Healthchecks and Troubleshooting

Check container health status:

```bash
docker inspect --format='{{json .State.Health}}' raganything | jq
```

View live container logs:

```bash
docker compose logs -f raganything
```
