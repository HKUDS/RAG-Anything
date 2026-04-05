from __future__ import annotations

from src.workbench.experiments.base import PostprocessingExperimentDefinition
from src.workbench.metrics import POSTPROCESSING_METRIC_PLAN

POSTPROCESSING_EXPERIMENTS = {
    "postprocess_identity": PostprocessingExperimentDefinition(
        id="postprocess_identity",
        description="No-op answer postprocessing baseline",
        category="postprocessing",
        metric_plan=POSTPROCESSING_METRIC_PLAN,
        base_experiment_id="exp1_baseline_docling",
        postprocess_strategy="identity",
        notes="Scaffold for future answer cleanup / compression comparisons.",
        tags=["postprocess", "baseline"],
    ),
    "postprocess_brief": PostprocessingExperimentDefinition(
        id="postprocess_brief",
        description="Brief answer cleanup scaffold",
        category="postprocessing",
        metric_plan=POSTPROCESSING_METRIC_PLAN,
        base_experiment_id="exp1_baseline_docling",
        postprocess_strategy="brief_grounded_rewrite",
        notes="Scaffold for future answer brevity experiments.",
        tags=["postprocess", "brevity"],
    ),
}
