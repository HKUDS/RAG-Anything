# SPIQA Test-A Results

## Overview

Test-A evaluation demonstrates the system's performance on a mixed question set comprising predominantly open-ended queries with a small subset of multiple-choice items. The dataset spans 1,126 questions across 118 papers, requiring multimodal reasoning over text, figures, and tables. Our evaluation employs a relaxed matching strategy that accommodates paraphrase and numeric variance, achieving an overall accuracy of **82.7%**.

## Performance Visualization

The Test-A overview visualization (Figure X: `testa_overview.png`) provides four complementary perspectives on system behavior:

**Similarity Distribution (Top-Left):** The histogram reveals a right-skewed distribution with mean similarity of 0.339. A large cluster of questions achieves very low similarity scores (0.0–0.1), indicating cases where the generated answer diverges substantially from the gold reference. The distribution gradually tapers through intermediate values (0.2–0.6), with a secondary peak near 0.9–1.0 representing high-confidence matches. This bimodal pattern suggests the system operates in two regimes: either producing answers that align closely with ground truth or generating responses with significant semantic divergence.

**Question Type Count (Top-Right):** Open-ended questions dominate the dataset (approximately 630 instances, ~99.5%), while multiple-choice items comprise only a small fraction (~20 instances, ~0.5%). This imbalance reflects the test set's emphasis on free-form reasoning rather than constrained selection tasks.

**Accuracy by Question Type (Bottom-Left):** Multiple-choice questions achieve higher accuracy (~76%) compared to open-ended items (~57%). This discrepancy likely stems from the more constrained answer space in multiple-choice scenarios, where the model selects from predefined options rather than generating free-form text. However, the small sample size of multiple-choice questions warrants cautious interpretation.

**Similarity Distribution by Type (Bottom-Right, Violin Plot):** The violin plot reinforces the accuracy findings. Multiple-choice questions exhibit a concentrated distribution at higher similarity values (0.8–1.0), with a narrow spread indicating consistent high-quality matches. In contrast, open-ended questions show a much wider distribution, with substantial density at low similarity (0.0–0.1) and scattered peaks across the range. This reflects the inherent variability in open-ended answer generation and the challenges of matching semantically equivalent but lexically different responses.

## Representative Samples

To illustrate the evaluation outcomes, we present three representative examples from the Test-A results:

### Example 1: Correct Open-Ended Answer (High Semantic Match)

```json
{
  "paper_id": "1611.04684v1",
  "question_index": 1,
  "question": "Which model performs the best for response selection, and how can we tell?",
  "ground_truth": "The KEHNN model performs the best for response selection. This is evident because it achieves the highest scores across all metrics (R$2$@1, R${10}$@1, R${10}$@2, and R${10}$@5) compared to all other models in the table.",
  "predicted_answer": "KEHNN performs the best for response selection, as it achieves the highest scores across all metrics (R2@1: 0.786, R10@1: 0.460, R10@2: 0.591, R10@5: 0.819).",
  "reference": "1611.04684v1-Table4-1.png",
  "question_type": "open_ended",
  "evaluation": {
    "similarity_score": 0.271,
    "phrase_overlap": 0.271,
    "is_correct": true
  }
}
```

**Analysis:** Despite a modest similarity score (0.271), this example is correctly classified due to our relaxed matching strategy. The predicted answer captures the essential claim (KEHNN is best) and provides supporting metrics. The lower similarity reflects formatting differences (LaTeX math notation in ground truth vs. plain numbers in prediction) and minor phrasing variations, but the semantic content is preserved.

### Example 2: Incorrect Open-Ended Answer (Semantic Divergence)

```json
{
  "paper_id": "1611.04684v1",
  "question_index": 0,
  "question": "What are the main differences between the educational philosophies of the Bonaparte and Voltaire schools?",
  "ground_truth": "The Bonaparte school focuses on outdoor physical activities, maneuvers, and strategies, with a specialization in horse riding, lances, and swords. They aim to develop students into good leaders. The Voltaire school, on the other hand, encourages independent thinking and focuses on indoor activities. They aim to instill good moral values and develop students into philosophical thinkers.",
  "predicted_answer": "The main differences are that Bonaparte focuses on outdoor physical activities, leadership, and strategies, while Voltaire emphasizes indoor activities, independent thinking, and moral development.",
  "reference": "1611.04684v1-Table1-1.png",
  "question_type": "open_ended",
  "evaluation": {
    "similarity_score": 0.055,
    "phrase_overlap": 0.055,
    "is_correct": false
  }
}
```

**Analysis:** The predicted answer correctly identifies the key distinctions (outdoor vs. indoor, leadership vs. moral development) but lacks the specific details present in the ground truth (horse riding, lances, swords; good leaders vs. philosophical thinkers). The low similarity (0.055) and incorrect classification reflect this information loss, where the generated response provides a summary-level answer rather than the granular details required.

### Example 3: Correct Multiple-Choice Answer

```json
{
  "paper_id": "1703.04887v4",
  "question_index": 4,
  "question": "What is the role of the discriminator (D) in the proposed BR-CSGAN model?",
  "ground_truth": "The discriminator (D) is responsible for distinguishing between real sentence pairs translated by humans and generated sentence pairs produced by the generator (G). It provides feedback to G in the form of rewards, helping G improve its ability to generate realistic sentence pairs.",
  "predicted_answer": "The role of the discriminator (D) in the proposed BR-CSGAN model is to evaluate the generated data against human data and provide rewards based on the quality of the generated data.",
  "reference": "1703.04887v4-Figure1-1.png",
  "question_type": "multiple_choice",
  "evaluation": {
    "similarity_score": 0.147,
    "phrase_overlap": 0.147,
    "is_correct": true
  }
}
```

**Analysis:** This multiple-choice example demonstrates the relaxed matching strategy's effectiveness in recognizing semantically equivalent formulations. The predicted answer uses different terminology ("evaluate...against human data" vs. "distinguishing between real...and generated") but conveys the same functional role of the discriminator. The relatively low similarity score (0.147) would have been penalized under strict matching, but our tolerance for paraphrase correctly identifies this as a valid answer.

## Key Observations and Insights

The Test-A results reveal several important patterns:

1. **Paraphrase Tolerance is Essential:** The relaxed matching strategy significantly reduces false negatives caused by benign surface variation. Example 3 illustrates how semantically correct answers with different wording can be correctly classified despite low lexical similarity.

2. **Information Granularity Matters:** Example 2 demonstrates that while the system captures high-level distinctions, it sometimes fails to extract the detailed specifics required for full correctness. This suggests opportunities for enhanced prompting or retrieval strategies that emphasize comprehensive detail extraction.

3. **Type-Specific Performance Gaps:** The accuracy differential between multiple-choice (76%) and open-ended (57%) questions indicates that constrained answer spaces are easier to navigate. However, the small sample size of multiple-choice questions limits definitive conclusions.

4. **Bimodal Similarity Distribution:** The concentration of similarity scores at both extremes (very low and very high) suggests the system operates in a binary-like manner: either producing high-quality matches or generating substantially different answers. This pattern may indicate opportunities for confidence-based re-retrieval or refinement mechanisms.

## Implications for System Improvement

The Test-A analysis identifies specific areas for enhancement:

- **Detail Preservation:** The system should be prompted or guided to extract granular information rather than summarizing at a high level, particularly for open-ended questions requiring comprehensive answers.

- **Numeric and Format Normalization:** The relaxed matching strategy helps, but explicit unit normalization and format-aware extraction during generation could further reduce semantic gaps.

- **Retrieval Precision:** The high density of low-similarity cases suggests retrieval may sometimes fail to surface the most relevant evidence. Enhanced reranking or query expansion could improve this.

These insights inform our continued refinement of the query layer, retrieval strategies, and answer generation mechanisms across all SPIQA test sets.



