from __future__ import annotations

from src.workbench.experiments.base import RetrievalExperimentDefinition
from src.workbench.metrics import RETRIEVAL_METRIC_PLAN

BASE_PIPELINE_EXPERIMENTS = [
    "exp1_baseline_mineru_cloud_openai",
    "exp2_default_mineru_cloud_ollama",
    "exp4_medical_scope_mineru_cloud_ollama",
    # "exp5_medical_scope_mineru_ollama_radgraph_xl",
    # "exp6_medical_scope_mineru_ollama_iter_ade",
    # "exp7_medical_scope_mineru_ollama_iter_scierc",
    # "exp8_default_mineru_ollama_radgraph_xl",
    # "exp9_default_mineru_ollama_iter_ade",
    # "exp10_default_mineru_ollama_iter_scierc",
]

QUERY_MODES = ["mix", "naive", "local", "global"]
RERANK_PHASE_BASE_EXPERIMENTS = [
    "exp1_baseline_mineru_cloud_openai",
    "exp2_default_mineru_cloud_ollama",
    "exp4_medical_scope_mineru_cloud_ollama",
]
RERANK_PHASE_QUERY_MODES = ["mix", "naive"]
BGE_RERANKER = "BAAI/bge-reranker-v2-m3"

RETRIEVAL_EXPERIMENTS: dict[str, RetrievalExperimentDefinition] = {}

for base_experiment_id in BASE_PIPELINE_EXPERIMENTS:
    for query_mode in QUERY_MODES:
        experiment_id = f"retrieval_{base_experiment_id}_{query_mode}"
        RETRIEVAL_EXPERIMENTS[experiment_id] = RetrievalExperimentDefinition(
            id=experiment_id,
            description=f"Retrieval benchmark for {base_experiment_id} using {query_mode} mode without reranker.",
            category="retrieval",
            metric_plan=RETRIEVAL_METRIC_PLAN,
            base_experiment_id=base_experiment_id,
            query_mode=query_mode,
            reranker_name=None,
            retrieval_kwargs={"enable_rerank": False},
            notes=(
                "Phase A retrieval benchmark. No reranker. "
                "Uses cached gold QA evidence from datasets/pipeline_qa/gold_qa."
            ),
            tags=["retrieval", query_mode, "phase_a", "no_rerank"],
        )

for base_experiment_id in RERANK_PHASE_BASE_EXPERIMENTS:
    for query_mode in RERANK_PHASE_QUERY_MODES:
        experiment_id = f"retrieval_{base_experiment_id}_{query_mode}_bge_reranker_v2_m3"
        RETRIEVAL_EXPERIMENTS[experiment_id] = RetrievalExperimentDefinition(
            id=experiment_id,
            description=(
                f"Retrieval benchmark for {base_experiment_id} using {query_mode} mode "
                f"with {BGE_RERANKER}."
            ),
            category="retrieval",
            metric_plan=RETRIEVAL_METRIC_PLAN,
            base_experiment_id=base_experiment_id,
            query_mode=query_mode,
            reranker_name=BGE_RERANKER,
            retrieval_kwargs={"enable_rerank": True},
            notes=(
                "Phase B retrieval benchmark. Keeps the same retrieval budget as phase A "
                "and adds a local BGE reranker over retrieved chunks."
            ),
            tags=["retrieval", query_mode, "phase_b", "rerank", "bge-reranker-v2-m3"],
        )
