FROM python:3.11-slim

LABEL org.opencontainers.image.title="RAG-Anything"
LABEL org.opencontainers.image.description="All-in-One Multimodal RAG System"

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY . .

# 前端构建
WORKDIR /app/frontend
RUN npm install && npm run build

WORKDIR /app

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

EXPOSE 8000

# 启动命令
CMD ["python", "server.py"]
