from .models import MetricDefinition, MetricPlan

PARSER_METRIC_PLAN = MetricPlan(
    summary=(
        "Parser phase-1 benchmark is intentionally label-free. It tracks only the five headline metrics "
        "that give fast insight into parser quality, multimodal coverage, downstream cost, and speed."
    ),
    metrics=[
        MetricDefinition(
            "parse_success_rate",
            "Parse Success Rate",
            "Share of documents parsed successfully. This is the minimum production-readiness gate.",
            "quality",
            hardware_sensitive=False,
            primary=True,
        ),
        MetricDefinition(
            "modality_coverage_profile",
            "Modality Coverage Profile",
            "Observed multimodal coverage from the parsed output: text blocks per page, and tables/figures/equations per 100 pages.",
            "quality",
            hardware_sensitive=False,
            primary=True,
        ),
        MetricDefinition(
            "noise_ratio",
            "Noise Ratio",
            "Heuristic fraction of extracted text judged as parser junk such as page numbers, repeated headers, bbox-like traces, or OCR garbage.",
            "quality",
            hardware_sensitive=False,
            higher_is_better=False,
            primary=True,
        ),
        MetricDefinition(
            "tokens_per_page",
            "Normalized Tokens/Page",
            "Token volume per observed page after normalization; a proxy for downstream chunking/indexing/LLM cost.",
            "efficiency",
            hardware_sensitive=False,
            higher_is_better=False,
            primary=True,
        ),
        MetricDefinition(
            "median_seconds_per_page",
            "Median Sec/Page",
            "Median parser runtime per observed page on the current machine. Useful operationally, but compare only within the same environment.",
            "speed",
            hardware_sensitive=True,
            higher_is_better=False,
            primary=True,
        ),
    ],
    insight_questions=[
        "Which parser is stable enough to trust in production?",
        "Which parser preserves richer multimodal structure without producing too much junk?",
        "Which parser gives the best speed-versus-downstream-cost tradeoff?",
    ],
)
