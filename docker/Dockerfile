# syntax=docker/dockerfile:1.7
#
# RAG-Anything, CPU image.
#
# Build from the repository root so the working tree is installed:
#
#   docker build -f docker/Dockerfile -t raganything:cpu .
#   docker run --rm -it --env-file .env -v raganything-data:/data raganything:cpu
#
# See docs/docker.md for the full description of build arguments and volumes.

FROM python:3.12-slim-bookworm

ARG EXTRAS=all
ARG BAKE_MODELS=1
ARG WITH_OFFICE=1
ARG WITH_MEDIA=1
ARG WITH_CJK=0
ARG PUID=10001
ARG PGID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/opt/models/hf \
    TIKTOKEN_CACHE_DIR=/opt/models/tiktoken \
    MINERU_MODEL_SOURCE=local \
    MINERU_DEVICE_MODE=cpu

# System packages:
#   libgl1, libglib2.0-0     OpenCV, used by MinerU and scenedetect
#   pango/cairo/gdk-pixbuf   WeasyPrint, used by the markdown extra
#   libreoffice-*            the office extra shells out to soffice
#   ffmpeg                   the audio and video extras
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        fontconfig \
        fonts-dejavu-core \
        libcairo2 \
        libffi8 \
        libgdk-pixbuf-2.0-0 \
        libgl1 \
        libglib2.0-0 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        shared-mime-info; \
    if [ "$WITH_OFFICE" = "1" ]; then \
        apt-get install -y --no-install-recommends \
            default-jre-headless \
            libreoffice-calc \
            libreoffice-impress \
            libreoffice-writer; \
    fi; \
    if [ "$WITH_MEDIA" = "1" ]; then \
        apt-get install -y --no-install-recommends ffmpeg; \
    fi; \
    if [ "$WITH_CJK" = "1" ]; then \
        apt-get install -y --no-install-recommends fonts-noto-cjk; \
    fi; \
    fc-cache -f; \
    rm -rf /var/lib/apt/lists/*

# Install the CPU build of torch before anything else pulls it in. Resolving
# torch from PyPI on a CPU image drags in the CUDA wheels and roughly 3 GB of
# nvidia-* packages that are never used.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision

WORKDIR /src
COPY . /src

RUN --mount=type=cache,target=/root/.cache/pip \
    set -eux; \
    if [ "$EXTRAS" = "none" ]; then \
        pip install .; \
    else \
        pip install ".[${EXTRAS}]"; \
    fi; \
    pip install python-dotenv

# Keep the examples and helper scripts in the image, then drop the build tree.
RUN set -eux; \
    cp -r /src/examples /opt/raganything-examples; \
    cp /src/env.example /opt/raganything-examples/env.example; \
    cp -r /src/scripts /opt/raganything-scripts; \
    rm -rf /src

# Create the runtime user before downloading anything large. Running the
# downloads as this user avoids a recursive chown over the weights, which
# would duplicate the whole model directory into a second image layer.
RUN set -eux; \
    groupadd --gid "$PGID" rag; \
    useradd --create-home --uid "$PUID" --gid "$PGID" rag; \
    mkdir -p /data/input /data/output /data/rag_storage /opt/models; \
    chown -R rag:rag /data /opt/models /home/rag

USER rag

ENV HOME=/home/rag \
    OUTPUT_DIR=/data/output \
    WORKING_DIR=/data/rag_storage \
    PARSER=mineru \
    PARSE_METHOD=auto

# MinerU pipeline weights, roughly 2.5 GB. Baked in so the image parses
# without network access; set BAKE_MODELS=0 to fetch them at first use.
RUN set -eux; \
    if [ "$BAKE_MODELS" = "1" ]; then \
        mineru-models-download -s huggingface -m pipeline; \
    else \
        echo "Models not baked in; set MINERU_MODEL_SOURCE=huggingface at runtime."; \
    fi

# LightRAG tokenises with tiktoken, which otherwise downloads its encoding on
# first use and fails in an offline container. See docs/offline_setup.md.
RUN python /opt/raganything-scripts/create_tiktoken_cache.py

WORKDIR /data
VOLUME ["/data"]

COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["shell"]
