FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create working directory for RAG storage
RUN mkdir -p /app/rag_storage /app/output

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV WORKING_DIR=/app/rag_storage

# Expose port
EXPOSE 8000

# Default command
CMD ["python", "-c", "print('RAG-Anything container ready. Use as a library or run examples.')"]