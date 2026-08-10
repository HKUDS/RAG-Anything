# Network source overrides for restricted networks. Defaults keep the
# canonical upstreams; pass --build-arg to switch to a reachable mirror
# (e.g. DEBIAN_MIRROR_HOST=mirrors.aliyun.com, PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple).
ARG DEBIAN_MIRROR_HOST=deb.debian.org
ARG PIP_INDEX_URL=https://pypi.org/simple

FROM node:20-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# Bookworm still provides OpenJDK 17, which is required by the
# OpenDataLoader runtime. The floating slim tag moved to trixie, where that
# package is no longer available.
FROM python:3.11-slim-bookworm AS base

LABEL org.opencontainers.image.title="RAG-Anything"
LABEL org.opencontainers.image.description="All-in-One Multimodal RAG System"

ARG DEBIAN_MIRROR_HOST
ARG PIP_INDEX_URL

# Native dependencies include ffmpeg/ffprobe for video indexing. Debian's
# mirrors can drop an individual package fetch during a long LibreOffice
# install, so use HTTPS plus bounded APT and install-level retries.
RUN set -eux; \
    sed -i "s|http://deb.debian.org|https://${DEBIAN_MIRROR_HOST}|g" /etc/apt/sources.list.d/debian.sources; \
    printf 'Acquire::Retries "5";\nAcquire::http::Timeout "120";\nAcquire::https::Timeout "120";\n' > /etc/apt/apt.conf.d/80-network-retries; \
    for attempt in 1 2 3; do \
        if apt-get update && apt-get install -y --no-install-recommends \
            libreoffice \
            ffmpeg \
            libpq-dev \
            postgresql-client \
            gcc \
            libgl1 \
            libglib2.0-0 \
            libgomp1 \
            openjdk-17-jre-headless; then \
            break; \
        fi; \
        if [ "$attempt" = 3 ]; then exit 1; fi; \
        rm -rf /var/lib/apt/lists/*; \
        sleep "$((attempt * 5))"; \
    done; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 婵炴挻纰嶇换鍡欑矉?
COPY requirements.txt .
# BuildKit or a deployment host may inject PIP_CONSTRAINT/PIP_REQUIRE_HASHES.
# Install from the declared requirements source only; --isolated ignores those
# ambient settings without disabling Pip's integrity checks.
RUN python -m pip --isolated install --no-cache-dir --timeout 120 --retries 5 \
    --index-url ${PIP_INDEX_URL} \
    -r requirements.txt

# 闁圭厧鐡ㄥ濠氬极閵堝棛顩烽柨婵嗘川閸?
COPY . .

# 闂佸憡鎸哥粔鍫曨敂椤掑嫬鍑犻柛鏇ㄥ亞缁?
COPY --from=frontend-build /frontend/dist /app/frontend/dist

WORKDIR /app

# 闂佺顑冮崕閬嶅箖瀹ュ憘娑㈠焵椤掑嫬钃?
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

EXPOSE 8000

# 闂佸憡鍑归崹鐗堟叏閳哄懎宸濋柟瀛樺笚婵?
CMD ["python", "server.py"]

# Compatibility verification target for the OpenDataLoader runtime bundled in
# the default image. Build explicitly with:
# docker build --target opendataloader -t raganything:opendataloader .
FROM nginx:alpine AS frontend
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /frontend/dist /usr/share/nginx/html

FROM base AS opendataloader
RUN java -version 2>&1 | grep -Eq 'version "17\\.|openjdk 17\\.' \
    && python -c "from importlib.metadata import version; assert version('opendataloader-pdf') == '2.5.0'"

# Marker is intentionally isolated: marker-pdf requires Pillow<11 while the
# MinerU runtime in `base` requires Pillow>=11. Build and deploy this target
# as a separate parser worker image; never install marker-pdf into `base`.
FROM python:3.11-slim AS marker
ARG DEBIAN_MIRROR_HOST
ARG PIP_INDEX_URL
RUN sed -i "s|http://deb.debian.org|https://${DEBIAN_MIRROR_HOST}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libreoffice \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /marker
COPY raganything/parser/marker_worker.py /marker/marker_worker.py
RUN python -m pip --isolated install --no-cache-dir --timeout 120 --retries 5 \
    --index-url ${PIP_INDEX_URL} \
    "marker-pdf[full]>=1.8,<2.0" \
    "Pillow<11"
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/healthz', timeout=5)"
EXPOSE 8765
CMD ["python", "/marker/marker_worker.py"]

# Default app target includes PaddleOCR/OpenDataLoader and Java; Marker remains
# isolated in the dedicated `marker` target above.
FROM base AS default
