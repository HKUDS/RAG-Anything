import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv(override=True)

@dataclass
class EnvConfig:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL")
    ollama_api_key: str = os.getenv("OLLAMA_API_KEY", "ollama")
    llm_model: str = os.getenv("LLM_MODEL")
    vision_model: str = os.getenv("VISION_MODEL")
    embed_model: str = os.getenv("EMBEDDING_MODEL")
    embed_dim: int = int(os.getenv("EMBEDDING_DIM", 768))
    
    input_dir: str = os.getenv("INPUT_DIR", "./data_test")
    output_base_dir: str = os.getenv("OUTPUT_BASE_DIR", "./benchmark_outputs")
    report_file: str = os.getenv("REPORT_FILE", "./benchmark_report.csv")
    max_workers: int = int(os.getenv("MAX_WORKERS", 1))

@dataclass
class ExperimentDef:
    id: str
    description: str
    # Các tham số truyền xuống LightRAG (để chỉnh chunk size, gleaning...)
    lightrag_kwargs: Dict[str, Any] = field(default_factory=dict)
    # Các tham số truyền xuống RAGAnything config (nếu cần)
    raganything_kwargs: Dict[str, Any] = field(default_factory=dict)
    custom_prompts: Dict[str, str] = field(default_factory=dict)

ENV = EnvConfig()