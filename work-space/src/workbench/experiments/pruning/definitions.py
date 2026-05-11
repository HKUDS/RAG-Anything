from __future__ import annotations

from src.workbench.experiments.base import PruningExperimentDefinition
from src.workbench.metrics import PRUNING_METRIC_PLAN

BASE_PIPELINE_EXPERIMENTS = [
    "exp1_baseline_mineru_cloud_openai",
    "exp2_default_mineru_ollama",
    "exp4_medical_scope_mineru_ollama",
    "exp5_medical_scope_mineru_ollama_radgraph_xl",
    "exp6_medical_scope_mineru_ollama_iter_ade",
    "exp7_medical_scope_mineru_ollama_iter_scierc",
    "exp8_default_mineru_ollama_radgraph_xl",
    "exp9_default_mineru_ollama_iter_ade",
    "exp10_default_mineru_ollama_iter_scierc",
]

PRUNING_METHODS = [
    ("baseline", "baseline_degree_pagerank"),
    ("hybrid", "hybrid_community_centrality"),
    ("personalized_pagerank", "personalized_pagerank_document_aware"),
    ("embedding_semantic_summary", "embedding_semantic_summary_with_approximate_linking"),
    ("llm_strict_topk", "llm_strict_topk"),
    ("llm_strict_topk_safe_merge", "llm_strict_topk_safe_merge"),
]

DEFAULT_TOP_K = 50
DEFAULT_CANDIDATE_POOL_SIZE = 90

PRUNING_EXPERIMENTS: dict[str, PruningExperimentDefinition] = {}

for base_experiment_id in BASE_PIPELINE_EXPERIMENTS:
    for method_id, method_label in PRUNING_METHODS:
        experiment_id = f"pruning_{base_experiment_id}_{method_id}_top{DEFAULT_TOP_K}"
        notes = (
            "FE-only graph pruning benchmark. "
            "Does not modify storage or retrieval data. "
            "Produces a compact graph artifact for Streamlit visualization."
        )
        if method_id.startswith("llm_"):
            notes += (
                " Uses a strict OpenAI-based graph summarization prompt over a heuristic candidate pool "
                "and may perform safe virtual merges for display only."
            )

        PRUNING_EXPERIMENTS[experiment_id] = PruningExperimentDefinition(
            id=experiment_id,
            description=(
                f"Pruning benchmark for {base_experiment_id} using {method_label} "
                f"with top_k={DEFAULT_TOP_K}."
            ),
            category="pruning",
            metric_plan=PRUNING_METRIC_PLAN,
            base_experiment_id=base_experiment_id,
            pruning_method=method_id,
            top_k=DEFAULT_TOP_K,
            candidate_pool_size=DEFAULT_CANDIDATE_POOL_SIZE,
            pruning_kwargs={},
            llm_model_name=None,
            notes=notes,
            tags=["pruning", method_id, f"topk-{DEFAULT_TOP_K}"],
        )
