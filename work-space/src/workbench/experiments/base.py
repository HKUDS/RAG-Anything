from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.workbench.metrics.models import MetricPlan


@dataclass
class BaseExperimentDefinition:
    id: str
    description: str
    category: str
    metric_plan: MetricPlan
    notes: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class PipelineExperimentDefinition(BaseExperimentDefinition):
    provider: str = "ollama"
    parser: Optional[str] = None
    parse_method: Optional[str] = None
    input_dir_override: Optional[str] = None
    parser_kwargs: Dict[str, Any] = field(default_factory=dict)
    use_gliner: bool = False
    gliner_labels: list = field(default_factory=list)
    lightrag_kwargs: Dict[str, Any] = field(default_factory=dict)
    raganything_kwargs: Dict[str, Any] = field(default_factory=dict)
    custom_prompts: Dict[str, str] = field(default_factory=dict)
    profile_name: str = ""
    legacy_alias: bool = False


@dataclass
class ParserBenchmarkExperimentDefinition(BaseExperimentDefinition):
    parser: str = "mineru"
    parse_method: str = "auto"
    parser_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalExperimentDefinition(BaseExperimentDefinition):
    base_experiment_id: str = ""
    query_mode: str = "mix"
    reranker_name: Optional[str] = None
    judge_strategy: str = "llm_judged"
    retrieval_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PruningExperimentDefinition(BaseExperimentDefinition):
    base_experiment_id: str = ""
    pruning_method: str = "hybrid"
    top_k: int = 50
    candidate_pool_size: int = 90
    pruning_kwargs: Dict[str, Any] = field(default_factory=dict)
    llm_model_name: Optional[str] = None


@dataclass
class PostprocessingExperimentDefinition(BaseExperimentDefinition):
    base_experiment_id: str = ""
    postprocess_strategy: str = "identity"
    qa_judge_strategy: str = "gemini"
    postprocess_kwargs: Dict[str, Any] = field(default_factory=dict)
