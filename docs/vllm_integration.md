# vLLM Integration Guide for RAG-Anything

[vLLM](https://github.com/vllm-project/vllm) is a high-throughput, memory-efficient inference engine for LLMs. It exposes an OpenAI-compatible API, making it a drop-in backend for RAG-Anything in production environments.

## Why vLLM?

| Feature | vLLM | Ollama | LM Studio |
|---------|------|--------|-----------|
| **Continuous batching** | ✅ | ❌ | ❌ |
| **PagedAttention** | ✅ | ❌ | ❌ |
| **Tensor parallelism** | ✅ | ❌ | ❌ |
| **Production throughput** | ✅ High | Moderate | Low |
| **Quantization (AWQ/GPTQ/FP8)** | ✅ | ✅ (GGUF) | ✅ (GGUF) |
| **Multi-GPU support** | ✅ Native | Limited | ❌ |
| **Ease of setup** | Moderate | Easy | Easy |
| **GUI** | ❌ | ❌ | ✅ |

**Choose vLLM when:** You need production-grade throughput, serve multiple concurrent users, or run large models across multiple GPUs.

## Prerequisites

1. **NVIDIA GPU(s)** with CUDA support (compute capability ≥ 7.0)
2. **Python 3.9+**
3. **vLLM installed:**
   ```bash
   pip install vllm
   ```
4. **RAG-Anything installed:**
   ```bash
   pip install raganything
   ```

## Quick Start

### 1. Start vLLM Server

**Chat/Completion model:**
```bash
vllm serve Qwen/Qwen2.5-72B-Instruct \
    --tensor-parallel-size 4 \
    --max-model-len 32768 \
    --port 8000
```

**Embedding model** (separate process, different port):
```bash
vllm serve BAAI/bge-m3 \
    --task embedding \
    --port 8001
```

### 2. Configure Environment

Create a `.env` file:

```bash
### vLLM Configuration
LLM_BINDING=vllm
LLM_MODEL=Qwen/Qwen2.5-72B-Instruct
LLM_BINDING_HOST=http://localhost:8000/v1
LLM_BINDING_API_KEY=token-abc123

### Embedding via vLLM
EMBEDDING_BINDING=vllm
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
EMBEDDING_BINDING_HOST=http://localhost:8001/v1
EMBEDDING_BINDING_API_KEY=token-abc123
```

### 3. Run the Example

```bash
cd examples
python vllm_integration_example.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BINDING` | — | Set to `vllm` |
| `LLM_MODEL` | `Qwen/Qwen2.5-72B-Instruct` | Model name (must match what vLLM is serving) |
| `LLM_BINDING_HOST` | `http://localhost:8000/v1` | vLLM API base URL |
| `LLM_BINDING_API_KEY` | `token-abc123` | API key (vLLM default: any non-empty string) |
| `EMBEDDING_BINDING` | — | Set to `vllm` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding model name |
| `EMBEDDING_DIM` | `1024` | Embedding dimensions |
| `EMBEDDING_BINDING_HOST` | `http://localhost:8001/v1` | Embedding endpoint URL |
| `EMBEDDING_BINDING_API_KEY` | `token-abc123` | Embedding API key |

## Model Configurations

### Qwen 2.5 (Recommended for RAG)
```bash
vllm serve Qwen/Qwen2.5-72B-Instruct \
    --tensor-parallel-size 4 \
    --max-model-len 32768
```

### Mistral / Mixtral
```bash
vllm serve mistralai/Mixtral-8x7B-Instruct-v0.1 \
    --tensor-parallel-size 2 \
    --max-model-len 32768
```

### Llama 3.1 70B
```bash
vllm serve meta-llama/Llama-3.1-70B-Instruct \
    --tensor-parallel-size 4 \
    --max-model-len 8192
```

### With AWQ Quantization (reduced memory)
```bash
vllm serve Qwen/Qwen2.5-72B-Instruct-AWQ \
    --tensor-parallel-size 2 \
    --quantization awq \
    --max-model-len 32768
```

### With GPTQ Quantization
```bash
vllm serve TheBloke/Mixtral-8x7B-Instruct-v0.1-GPTQ \
    --tensor-parallel-size 2 \
    --quantization gptq
```

## Performance Tips

### Tensor Parallelism
Distribute large models across GPUs. Set `--tensor-parallel-size` to the number of GPUs:
```bash
# 4x A100 80GB → can serve 72B models in full precision
vllm serve Qwen/Qwen2.5-72B-Instruct --tensor-parallel-size 4
```

### GPU Memory Utilization
Increase if you have headroom (default 0.9):
```bash
vllm serve ... --gpu-memory-utilization 0.95
```

### Max Model Length
Reduce if you don't need full context (saves memory):
```bash
# RAG chunks are typically <4K tokens; 8192 is often sufficient
vllm serve ... --max-model-len 8192
```

### Concurrency
vLLM handles batching automatically. On the RAG-Anything side, increase `MAX_ASYNC` in your `.env`:
```bash
MAX_ASYNC=16  # vLLM handles concurrent requests efficiently
```

### Speculative Decoding (vLLM ≥ 0.4)
Use a small draft model to speed up generation:
```bash
vllm serve Qwen/Qwen2.5-72B-Instruct \
    --speculative-model Qwen/Qwen2.5-0.5B-Instruct \
    --num-speculative-tokens 5 \
    --tensor-parallel-size 4
```

## Embedding Options

### Option A: vLLM Embedding Server (Recommended)
Run a dedicated vLLM instance for embeddings:
```bash
vllm serve BAAI/bge-m3 --task embedding --port 8001
```

### Option B: Use Ollama for Embeddings
If you already run Ollama, you can mix backends:
```bash
EMBEDDING_BINDING=ollama
EMBEDDING_MODEL=bge-m3:latest
EMBEDDING_BINDING_HOST=http://localhost:11434
```

### Option C: OpenAI Embeddings
Use OpenAI's embedding API alongside vLLM for chat:
```bash
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIM=3072
EMBEDDING_BINDING_HOST=https://api.openai.com/v1
EMBEDDING_BINDING_API_KEY=sk-...
```

## Architecture

```
┌──────────────────────┐
│   RAG-Anything       │
│  (Document Processing│
│   + Query Engine)    │
└──────┬───────────────┘
       │ OpenAI-compatible API
       ▼
┌──────────────────────┐     ┌──────────────────────┐
│  vLLM Chat Server    │     │  vLLM Embedding Server│
│  :8000/v1            │     │  :8001/v1             │
│  (Qwen-72B, etc.)   │     │  (bge-m3, etc.)       │
└──────────────────────┘     └──────────────────────┘
       │                            │
       ▼                            ▼
┌──────────────────────────────────────────────┐
│              GPU Cluster                      │
│   PagedAttention · Continuous Batching        │
│   Tensor Parallelism · Quantization           │
└──────────────────────────────────────────────┘
```

## Troubleshooting

### Connection Refused
```
❌ Connection failed: Connection refused
```
- Ensure vLLM is running: `curl http://localhost:8000/v1/models`
- Check the port matches your `LLM_BINDING_HOST`
- Wait for model loading to complete (large models can take minutes)

### Out of Memory
```
torch.cuda.OutOfMemoryError
```
- Use quantized models (`--quantization awq` or `gptq`)
- Reduce `--max-model-len`
- Increase `--tensor-parallel-size` (more GPUs)
- Lower `--gpu-memory-utilization`

### Model Not Found
```
Model 'xxx' not found
```
- `LLM_MODEL` must match the model name vLLM is serving exactly
- Check available models: `curl http://localhost:8000/v1/models`

### Slow First Request
This is normal — vLLM compiles CUDA kernels on first use. Subsequent requests are fast.
