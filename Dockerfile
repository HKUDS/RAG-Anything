# ==============================================================================
# Multi-stage Dockerfile for RAG-Anything
# Stage 1: Build virtual environment and compile dependencies
# Stage 2: Minimal, secure runtime container with unprivileged user
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Builder
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install build-time dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create isolated Python virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Copy project metadata first for caching layer
COPY pyproject.toml README.md ./
COPY raganything ./raganything

# Install project and optional dependencies
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --upgrade pip setuptools wheel && \
    pip install torch torchvision --index-url "$TORCH_INDEX_URL" && \
    pip install .[all]

# ------------------------------------------------------------------------------
# Stage 2: Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    RAG_DIR="/app/rag_storage" \
    OUTPUT_DIR="/app/parser_output"

# Install essential runtime shared libraries and utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    libgomp1 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    ffmpeg \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    poppler-utils \
    pandoc \
    curl \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# BuildKit mounts the source read-only; copy it and set ownership in one layer.
# This also avoids repeatedly copying the large venv with native snapshotters.
RUN --mount=type=bind,target=/src \
    groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -m -d /home/appuser -s /bin/bash appuser && \
    mkdir -p /app/rag_storage /app/parser_output /app/inputs /home/appuser/.cache && \
    cp -R /src/raganything /src/examples /app/ && \
    cp /src/pyproject.toml /src/README.md /app/ && \
    cp /src/docker/entrypoint.sh /usr/local/bin/entrypoint.sh && \
    chmod +x /usr/local/bin/entrypoint.sh && \
    chown -R appuser:appuser /app /home/appuser

WORKDIR /app
USER appuser

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "examples/raganything_example.py", "--help"]
