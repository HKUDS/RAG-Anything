import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv(override=True)

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
    output_base_dir: str = os.getenv("OUTPUT_BASE_DIR", "./benchmark_outputs")
    report_file: str = os.getenv("REPORT_FILE", "./benchmark_report.csv")
    max_workers: int = int(os.getenv("MAX_WORKERS", 1))

@dataclass
class ExperimentDef:
    id: str
    description: str
    provider: str = "ollama" 
    lightrag_kwargs: Dict[str, Any] = field(default_factory=dict)
    raganything_kwargs: Dict[str, Any] = field(default_factory=dict)
    custom_prompts: Dict[str, str] = field(default_factory=dict)

ENV = EnvConfig()