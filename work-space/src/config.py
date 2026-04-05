import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)

@dataclass
class EnvConfig:
    # Ollama settings
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL")
    ollama_api_key: str = os.getenv("OLLAMA_API_KEY")
    ollama_llm: str = os.getenv("OLLAMA_LLM_MODEL")
    ollama_vision: str = os.getenv("OLLAMA_VISION_MODEL")
    ollama_embed: str = os.getenv("OLLAMA_EMBED_MODEL")
    ollama_dim: int = int(os.getenv("OLLAMA_EMBED_DIM", 768))
    
    # OpenAI settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY")
    openai_llm: str = os.getenv("OPENAI_LLM_MODEL")
    openai_vision: str = os.getenv("OPENAI_VISION_MODEL")
    openai_embed: str = os.getenv("OPENAI_EMBED_MODEL")
    openai_dim: int = int(os.getenv("OPENAI_EMBED_DIM", 3072))

    # System settings
    input_dir: str = os.getenv("INPUT_DIR", "./data_test")
    parser_benchmark_input_dir: str = os.getenv("PARSER_BENCHMARK_INPUT_DIR", "./datasets/parser_benchmark/raw_docs")
    output_base_dir: str = os.getenv("OUTPUT_BASE_DIR", "./benchmark_outputs")
    report_file: str = os.getenv("REPORT_FILE", "./benchmark_outputs/reports/pipeline_benchmark.csv")
    max_workers: int = int(os.getenv("MAX_WORKERS", 1))
    
    parser: str = os.getenv("PARSER", "mineru")
    parse_method: str = os.getenv("PARSE_METHOD", "auto")
    mineru_backend: str = os.getenv("MINERU_BACKEND", "hybrid-auto-engine")
    mineru_device: str = os.getenv("MINERU_DEVICE", "cuda")
    mineru_lang: str = os.getenv("MINERU_LANG", "en")
    mineru_source: str = os.getenv("MINERU_SOURCE", "huggingface")
    docling_device: str = os.getenv("DOCLING_DEVICE", "cuda")
    docling_ocr_lang: str = os.getenv("DOCLING_OCR_LANG", "en")
    kreuzberg_ocr_backend: str = os.getenv("KREUZBERG_OCR_BACKEND", "paddleocr")
    kreuzberg_ocr_language: str = os.getenv("KREUZBERG_OCR_LANGUAGE", "en")
    kreuzberg_ocr_use_gpu: bool = os.getenv("KREUZBERG_OCR_USE_GPU", "true").lower() in ("1", "true", "yes", "on")
    kreuzberg_ocr_model_tier: str = os.getenv("KREUZBERG_OCR_MODEL_TIER", "server")

    # Google Gemini settings
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")

    # Pruning settings for visualization
    pruning_max_nodes: int = int(os.getenv("PRUNING_MAX_NODES", 50))
    pruning_default_algorithm: str = os.getenv("PRUNING_DEFAULT_ALGORITHM", "hybrid")
    pruning_benchmark_report: str = os.getenv("PRUNING_BENCHMARK_REPORT", "./benchmark_outputs/reports/pruning_benchmark.csv")
    gold_dataset_file: str = os.getenv("GOLD_DATASET_FILE", "./benchmark_outputs/reports/gold_dataset.json")

    # Query settings
    query_default_mode: str = os.getenv("QUERY_DEFAULT_MODE", "mix")
    query_top_k: int = int(os.getenv("QUERY_TOP_K", 40))
    query_chunk_top_k: int = int(os.getenv("QUERY_CHUNK_TOP_K", 12))
    query_response_type: str = os.getenv("QUERY_RESPONSE_TYPE", "Multiple Paragraphs")
    query_enable_rerank: bool = os.getenv("QUERY_ENABLE_RERANK", "false").lower() in ("1", "true", "yes", "on")
ENV = EnvConfig()
