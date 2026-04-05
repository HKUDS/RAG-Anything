from .models import MetricDefinition, MetricPlan

POSTPROCESSING_METRIC_PLAN = MetricPlan(
    summary="Postprocessing experiments should measure answer cleanliness and factual retention with minimal dependence on runtime hardware.",
    metrics=[
        MetricDefinition("faithfulness", "Faithfulness", "Does the postprocessed answer stay aligned with source evidence?", "quality", hardware_sensitive=False, primary=True),
        MetricDefinition("completeness", "Completeness", "Does the answer retain the key details after postprocessing?", "quality", hardware_sensitive=False, primary=True),
        MetricDefinition("brevity_ratio", "Brevity Ratio", "Answer length reduction compared with the unprocessed answer.", "style", hardware_sensitive=False),
        MetricDefinition("postprocess_latency_seconds", "Postprocess Latency", "Observed runtime for postprocessing only.", "efficiency", hardware_sensitive=True, higher_is_better=False),
    ],
    insight_questions=[
        "Which postprocessing strategy improves readability without losing factual support?",
        "Which answer cleanup stage is worth keeping in production?",
    ],
)
