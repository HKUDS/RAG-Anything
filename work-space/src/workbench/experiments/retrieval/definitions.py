from __future__ import annotations

from src.workbench.experiments.base import RetrievalExperimentDefinition
from src.workbench.metrics import RETRIEVAL_METRIC_PLAN

RETRIEVAL_EXPERIMENTS = {
    "retrieval_mix_baseline": RetrievalExperimentDefinition(
        id="retrieval_mix_baseline",
        description="Baseline mix-mode retrieval evaluation scaffold",
        category="retrieval",
        metric_plan=RETRIEVAL_METRIC_PLAN,
        base_experiment_id="exp1_baseline_docling",
        query_mode="mix",
        notes="Scaffold for future retrieval/reranker benchmarking with MRR/Recall/Precision.",
        tags=["retrieval", "mix"],
    ),
    "retrieval_naive_baseline": RetrievalExperimentDefinition(
        id="retrieval_naive_baseline",
        description="Naive retrieval evaluation scaffold",
        category="retrieval",
        metric_plan=RETRIEVAL_METRIC_PLAN,
        base_experiment_id="exp1_baseline_docling",
        query_mode="naive",
        notes="Scaffold for chunk-only retrieval comparison.",
        tags=["retrieval", "naive"],
    ),
}
