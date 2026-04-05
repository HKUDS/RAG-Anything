from .models import MetricDefinition, MetricPlan

RETRIEVAL_METRIC_PLAN = MetricPlan(
    summary="Retriever/reranker experiments should prioritize ranking quality metrics that are less sensitive to hardware and model serving throughput.",
    metrics=[
        MetricDefinition("mrr", "MRR", "Mean Reciprocal Rank over labeled or LLM-judged evidence targets.", "ranking", hardware_sensitive=False, primary=True),
        MetricDefinition("recall_at_k", "Recall@K", "Coverage of relevant evidence in the top-K set.", "ranking", hardware_sensitive=False, primary=True),
        MetricDefinition("precision_at_k", "Precision@K", "Precision of the top-K evidence set.", "ranking", hardware_sensitive=False, primary=True),
        MetricDefinition("ndcg_at_k", "nDCG@K", "Gain-sensitive ranking quality.", "ranking", hardware_sensitive=False),
        MetricDefinition("retrieval_latency_seconds", "Retrieval Latency", "Observed runtime for retrieval + rerank stage.", "efficiency", hardware_sensitive=True, higher_is_better=False),
    ],
    insight_questions=[
        "Which retriever/reranker combination surfaces the right evidence earliest?",
        "Do gains in ranking quality justify added latency?",
    ],
)
