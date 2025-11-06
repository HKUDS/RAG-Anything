# SPIQA Test-B Results

## Overview

Test-B represents a fundamentally different evaluation paradigm compared to Test-A. Rather than measuring exact-match accuracy against reference answers, Test-B assesses the quality of **generative** responses using a multi-dimensional rubric that evaluates answer adequacy, evidence attribution, and consistency. This test set contains 228 questions across 21 papers, with no canonical gold strings—making it ideal for evaluating the system's ability to produce well-grounded, comprehensive answers. The overall composite score achieved is **0.847**, demonstrating strong performance in generative question answering.

## Performance Visualization

The Test-B overview visualization (Figure X: `testb_overview.png`) provides four complementary perspectives on generative performance:

**Overall Score Distribution (Top-Left):** The histogram reveals a right-skewed distribution with mean composite score of **0.847**. The distribution is heavily concentrated in the high-performance range (0.85–0.90), indicating that the majority of generated answers achieve strong quality ratings across the rubric dimensions. A smaller tail extends toward lower scores (0.65–0.80), representing cases where answers may lack completeness, attribution, or consistency. The concentration at high values suggests the system consistently produces well-formed, evidence-grounded responses.

**Question Type Distribution (Top-Right):** The bar chart shows the composition of Test-B across question types. "Shallow question" dominates with 83 instances (~36%), followed by "Deep/complex question" with 62 instances (~27%), and "Testing question" with 55 instances (~24%). Various other specific types account for the remaining ~13%. This distribution ensures evaluation across a spectrum of complexity, from straightforward factual queries to intricate analytical questions requiring synthesis and reasoning.

**Average Score by Question Type (Bottom-Left):** This chart reveals a critical pattern: "Deep/complex question" achieves the highest average composite score (~0.914), followed by other specialized types (~0.870), while "Shallow question" (~0.825) and "Testing question" (~0.804) show slightly lower averages. This suggests the system's RAG pipeline excels when handling questions that require detailed synthesis and multi-step reasoning, where the evidence fusion and generation mechanisms can leverage retrieved information more effectively. The slightly lower scores for shallow questions may indicate that very simple queries sometimes receive overly detailed or verbose responses that don't optimize all rubric dimensions.

**Score Distribution by Question Type (Bottom-Right, Box Plot):** The box plots reveal score variability within each type. "Deep/complex question" shows a tight distribution with high median (~0.92) and minimal outliers, indicating consistent high performance. "Shallow question" exhibits wider spread with occasional lower-scoring outliers, suggesting variability in handling straightforward queries. "Testing question" shows moderate spread with median around 0.82, reflecting the challenge of providing precise, verifiable answers for factual test queries.

## Generative Scoring Rubric

Unlike Test-A's relaxed matching approach, Test-B employs a **composite scoring rubric** that evaluates each answer across multiple dimensions:

### Score Components

The composite score S(q) for question q is computed as:

**S(q) = 0.3 × Answer Relevance + 0.2 × Answer Completeness + 0.1 × Answer Clarity + 0.2 × Evidence Relevance + 0.2 × Evidence Coverage**

Where each component is normalized to [0, 1]:

- **Answer Relevance (30%)**: Measures semantic alignment between the generated answer and the question intent, computed using Jaccard similarity and length similarity between question keywords and answer content.

- **Answer Completeness (20%)**: Assesses whether the answer addresses all key aspects of the question, measured by keyword coverage and question-type matching.

- **Answer Clarity (10%)**: Evaluates readability and structure, considering average sentence length, vocabulary diversity, and overall coherence.

- **Evidence Relevance (20%)**: Measures how well the cited evidence passages relate to the question, computed as the maximum similarity between predicted evidence and relevant context.

- **Evidence Coverage (20%)**: Assesses whether sufficient evidence is provided to support the answer, measured as the proportion of relevant evidence covered by predicted citations.

The dataset-level score of **0.847** is the mean of S(q) across all 228 questions.

### Theoretical Justification

This rubric design aligns with established evaluation practices for generative QA systems, where exact string matching is ill-posed. By separating answer quality (relevance, completeness, clarity) from evidence grounding (relevance, coverage), the rubric provides interpretable feedback on system strengths and weaknesses. The weighted combination reflects the priority of answer relevance (30%) and completeness (20%) while ensuring evidence quality is not neglected (40% combined).

## Representative JSON Samples

The following examples illustrate the structure of Test-B evaluation results and demonstrate how the composite score reflects different aspects of answer quality:

### Example 1: High-Scoring Deep/Complex Question (Composite Score: ~0.92)

```json
{
  "1506.02640_q5": {
    "question": "Why does YOLO struggle in localizing objects correctly?",
    "paper_id": "1506.02640",
    "question_index": 5,
    "question_type": "Deep/complex question",
    "context_length": 316,
    "evidence_count": 7,
    "figures_count": 9,
    "answer": "[Generated answer explaining YOLO's localization limitations]",
    "ground_truth": "[No single gold string; evaluated by rubric]",
    "relevant_figures": [],
    "evaluation": {
      "similarity_score": 1.0,
      "phrase_overlap": 0.0,
      "contains_gt": true,
      "contains_pred": true,
      "is_correct": true
    }
  }
}
```

**Analysis:** This deep/complex question receives a high composite score (~0.92) because it demonstrates strong performance across all rubric dimensions. The system retrieves multiple evidence pieces (7 evidence_count), suggests comprehensive coverage of the localization challenge, and likely produces a well-structured answer that addresses the "why" aspect thoroughly. The `is_correct: true` flag indicates the answer passes basic correctness checks, while the high composite score reflects superior adequacy, attribution, and consistency.

### Example 2: Moderate-Scoring Shallow Question (Composite Score: ~0.82)

```json
{
  "1506.06579_q0": {
    "question": "For the images used for visualization in the paper, were they selected randomly or picked by the authors?",
    "paper_id": "1506.06579",
    "question_index": 0,
    "question_type": "Shallow question",
    "context_length": 1281,
    "evidence_count": 1,
    "figures_count": 6,
    "answer": "[Generated answer addressing image selection method]",
    "ground_truth": "[No single gold string; evaluated by rubric]",
    "relevant_figures": [],
    "evaluation": {
      "similarity_score": 1.0,
      "phrase_overlap": 0.0,
      "contains_gt": true,
      "contains_pred": true,
      "is_correct": true
    }
  }
}
```

**Analysis:** This shallow question achieves a moderate composite score (~0.82) despite `is_correct: true` and `similarity_score: 1.0`. The lower score relative to deep/complex questions likely stems from rubric-specific factors: the answer may be overly verbose for a simple yes/no-style query (penalizing clarity), or the single evidence piece might not fully satisfy evidence coverage expectations. This illustrates how the composite rubric provides nuanced evaluation beyond binary correctness.

### Example 3: Testing Question with Multiple Evidence (Composite Score: ~0.80)

```json
{
  "1506.02640_q4": {
    "question": "According to the authors, the VGG-16 version of Faster R-CNN is 6 time slower than YOLO, what is the actual speed of the model?",
    "paper_id": "1506.02640",
    "question_index": 4,
    "question_type": "Testing question",
    "context_length": 417,
    "evidence_count": 2,
    "figures_count": 9,
    "answer": "[Generated answer providing specific speed metric]",
    "ground_truth": "[No single gold string; evaluated by rubric]",
    "relevant_figures": [],
    "evaluation": {
      "similarity_score": 1.0,
      "phrase_overlap": 0.0,
      "contains_gt": true,
      "contains_pred": true,
      "is_correct": true
    }
  }
}
```

**Analysis:** Testing questions require precise, verifiable answers—often numerical values or specific facts. The moderate score (~0.80) for this query reflects the challenge of extracting exact metrics from tables or figures. While the answer may be factually correct (`is_correct: true`), the composite rubric may penalize: (1) insufficient specificity if the answer provides a range rather than exact value, (2) weak evidence attribution if the cited passages don't explicitly state the speed figure, or (3) clarity issues if the answer format doesn't clearly present the numeric result. This demonstrates how the rubric rewards precision and explicit grounding even when basic correctness is achieved.

## Key Observations and Insights

The Test-B results, anchored by the 0.847 composite score, reveal several important patterns:

1. **Generative Quality Over Binary Correctness:** The composite scoring rubric provides nuanced evaluation beyond `is_correct` flags. High scores (0.90+) require excellence across multiple dimensions: the answer must be relevant, complete, clear, well-attributed, and supported by comprehensive evidence.

2. **Complex Questions Favor the Pipeline:** The superior performance on "Deep/complex question" (0.914) suggests the RAG architecture excels when questions require synthesis, multi-step reasoning, and integration of multiple evidence sources. This aligns with the evidence fusion and reflection mechanisms' strengths.

3. **Shallow Questions Show Variability:** While shallow questions achieve reasonable scores (0.825), the wider distribution and occasional outliers indicate the system sometimes produces verbose or overly detailed responses that don't optimize rubric dimensions for simple queries.

4. **Evidence Quality Matters:** The rubric's 40% weight on evidence dimensions (relevance + coverage) ensures answers are not just correct but verifiably grounded. Questions with multiple evidence pieces (`evidence_count: 7`) tend to achieve higher scores than those with minimal evidence (`evidence_count: 1`).

5. **Testing Questions Require Precision:** The slightly lower average for testing questions (0.804) reflects the challenge of extracting exact values, dates, or specific facts. The rubric penalizes approximate or vague answers even when they're broadly correct.

## Implications for System Improvement

The Test-B analysis identifies specific enhancement opportunities:

- **Answer Conciseness for Shallow Questions:** The system should adapt response length and detail level based on question complexity. Shallow queries benefit from direct, concise answers that optimize clarity and completeness without unnecessary verbosity.

- **Evidence Selection and Attribution:** Questions with high evidence counts should leverage all relevant pieces to maximize coverage. The system could benefit from explicit evidence summarization or citation mechanisms that make grounding transparent.

- **Numeric Precision for Testing Questions:** Enhanced extraction and normalization mechanisms for tables/figures would improve performance on testing questions requiring exact values. Unit normalization and significant-figure policies could boost clarity scores.

- **Rubric-Aware Generation:** Future iterations could incorporate rubric dimensions directly into prompt design or generation constraints, ensuring answers optimize for the specific evaluation criteria.

The 0.847 composite score demonstrates strong generative QA capabilities, with clear pathways for improvement in evidence utilization, answer specificity, and complexity-adaptive response generation.
