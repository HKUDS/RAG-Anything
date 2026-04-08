from .models import MetricDefinition, MetricPlan

RETRIEVAL_METRIC_PLAN = MetricPlan(
    summary="Retriever/reranker experiments should prioritize ranking quality metrics that are less sensitive to hardware and model serving throughput.",
    metrics=[
        MetricDefinition("mrr", "MRR", "Mean Reciprocal Rank over labeled or LLM-judged evidence targets.", "ranking", hardware_sensitive=False, primary=True),
        MetricDefinition("evidence_recall_at_5", "Evidence Recall@5", "Whether at least one gold evidence unit appears in the top-5 retrieved chunks.", "ranking", hardware_sensitive=False, primary=True),
        MetricDefinition("evidence_recall_at_10", "Evidence Recall@10", "Whether at least one gold evidence unit appears in the top-10 retrieved chunks.", "ranking", hardware_sensitive=False, primary=True),
        MetricDefinition("precision_at_5", "Precision@5", "Precision of the top-5 retrieved chunks against gold evidence heuristics.", "ranking", hardware_sensitive=False, primary=True),
    ],
    insight_questions=[
        "Which retriever/reranker combination surfaces the right evidence earliest?",
        "Which query mode gives the best retrieval quality before adding a reranker?",
    ],
)
