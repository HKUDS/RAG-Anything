LLM_STRICT_TOPK_SYSTEM_PROMPT = (
    "You are a strict knowledge-graph summarization expert for biomedical and technical documents. "
    "Your task is to choose the smallest FE graph that still preserves the most important concepts, "
    "evidence-linked entities, and explanatory structure for human inspection. "
    "Do not optimize for retrieval. Optimize for compact, meaningful visualization."
)


LLM_STRICT_TOPK_USER_PROMPT = """
Select the best display graph for a frontend graph visualization.

Rules:
- Choose at most {top_k} node IDs from the candidate pool.
- Prefer nodes that are central, evidence-linked, explanatory, and representative of different communities.
- Favor nodes that help a human quickly understand the document's main dataset, methods, findings, figures, and tables.
- Avoid generic or low-value nodes such as vague abstractions, parser artifacts, or redundant near-duplicates.
- Do not include chunk-like nodes unless they are absolutely necessary.
- Do not merge nodes in this task.
- Return strict JSON only.

Scoring priorities:
1. Core study concepts
2. Evidence-linked entities
3. Community/topic coverage
4. Multimodal anchors (important figures/tables/visual evidence)
5. Structural importance (bridge/central nodes)
6. Low redundancy

Candidate pool:
{candidate_json}

Return JSON:
{{
  "selected_node_ids": ["node_id_1", "node_id_2"],
  "rejected_node_ids": ["node_id_x"],
  "selection_rationale": "short explanation"
}}
"""


LLM_STRICT_TOPK_SAFE_MERGE_USER_PROMPT = """
Select the best compact display graph for a frontend graph visualization.

Rules:
- Choose at most {top_k} node IDs from the candidate pool.
- You may propose safe virtual merge groups only for semantically redundant nodes.
- Merge only when the nodes clearly refer to the same concept, alias, or redundant naming variant.
- Never merge merely because nodes form a cycle.
- Never merge distinct organs, datasets, methods, experimental conditions, or result concepts.
- Prefer compactness only if it does not hide important differences.
- Do not include chunk-like nodes unless absolutely necessary.
- Return strict JSON only.

Scoring priorities:
1. Core study concepts
2. Evidence-linked entities
3. Community/topic coverage
4. Multimodal anchors
5. Structural importance
6. Redundancy reduction without semantic loss

Candidate pool:
{candidate_json}

Return JSON:
{{
  "selected_node_ids": ["node_id_1", "node_id_2"],
  "merge_groups": [
    {{
      "merged_label": "display label",
      "member_node_ids": ["node_id_a", "node_id_b"],
      "reason": "why these nodes are safely mergeable",
      "confidence": 0.0
    }}
  ],
  "selection_rationale": "short explanation"
}}
"""
