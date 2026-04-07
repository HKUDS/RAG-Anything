from .models import MetricDefinition, MetricPlan

PIPELINE_METRIC_PLAN = MetricPlan(
    summary=(
        "Pipeline phase-1 metrics should stay compact: can the run finish, how expensive is it per page, "
        "how much graph expansion does it create, and how much multimodal content survives into indexing."
    ),
    metrics=[
        MetricDefinition(
            "pipeline_success_rate",
            "Pipeline Success Rate",
            "Fraction of files that successfully complete parse plus graph build.",
            "reliability",
            hardware_sensitive=False,
            primary=True,
        ),
        MetricDefinition(
            "end_to_end_seconds_per_page",
            "End-to-End Sec/Page",
            "Observed parse-to-graph wall time normalized by source pages.",
            "efficiency",
            hardware_sensitive=True,
            higher_is_better=False,
            primary=True,
        ),
        MetricDefinition(
            "output_tokens_per_page",
            "Output Tokens/Page",
            "Approximate LLM output-token cost normalized by source pages.",
            "cost",
            hardware_sensitive=False,
            higher_is_better=False,
            primary=True,
        ),
        MetricDefinition(
            "graph_expansion_profile",
            "Graph Expansion Profile",
            "Compact graph growth proxy: entities per chunk and relations per entity.",
            "structure",
            hardware_sensitive=False,
            primary=True,
        ),
        MetricDefinition(
            "multimodal_retention_profile",
            "Multimodal Retention Profile",
            "Compact modality retention proxy from the content entering indexing.",
            "structure",
            hardware_sensitive=False,
            primary=True,
        ),
    ],
    insight_questions=[
        "Does the medical prompt profile improve graph structure without exploding cost?",
        "How much environment/runtime overhead disappears when switching from local MinerU to MinerU cloud?",
        "Is multimodal retention preserved while graph expansion stays controlled?",
    ],
)
