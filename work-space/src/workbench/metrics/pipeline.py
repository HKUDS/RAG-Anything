from .models import MetricDefinition, MetricPlan

PIPELINE_METRIC_PLAN = MetricPlan(
    summary="Full-pipeline experiments should separate hardware-biased runtime metrics from graph-quality and answerability signals.",
    metrics=[
        MetricDefinition("chunks", "Chunks", "Number of chunks inserted into the retrieval substrate.", "structure", hardware_sensitive=False, primary=True),
        MetricDefinition("entities", "Entities", "Total extracted entities stored by the graph pipeline.", "structure", hardware_sensitive=False, primary=True),
        MetricDefinition("relations", "Relations", "Total extracted relations stored by the graph pipeline.", "structure", hardware_sensitive=False, primary=True),
        MetricDefinition("output_tokens", "LLM Output Tokens", "Approximate output-token cost from cached extraction calls.", "cost", hardware_sensitive=False, higher_is_better=False, primary=True),
        MetricDefinition("api_calls", "LLM API Calls", "Approximate extraction call count.", "cost", hardware_sensitive=False, higher_is_better=False, primary=True),
        MetricDefinition("graph_time_seconds", "Graph Time", "Observed indexing time after parsing.", "efficiency", hardware_sensitive=True, higher_is_better=False),
        MetricDefinition("total_time_seconds", "Total Time", "Observed end-to-end runtime.", "efficiency", hardware_sensitive=True, higher_is_better=False),
    ],
    insight_questions=[
        "Does a configuration achieve lower cost without collapsing graph coverage?",
        "Which setup builds the most useful graph per unit of extraction cost?",
        "How much of the gain comes from parser choice versus prompt/pipeline profile?",
    ],
)
