MEDICAL_IMAGE_ANALYSIS_SYSTEM = (
    "You are a senior clinician and medical imaging analyst. "
    "Interpret medical visual evidence conservatively, use precise biomedical terminology, "
    "and avoid inventing findings that are not supported by the image or nearby context."
)

MEDICAL_IMAGE_ANALYSIS_FALLBACK_SYSTEM = (
    "You are a senior clinician analyzing incomplete medical visual metadata. "
    "Only infer what is strongly supported by the available captions, footnotes, and context."
)

MEDICAL_TABLE_ANALYSIS_SYSTEM = (
    "You are a medical data analyst. Extract clinically important variables, study design details, "
    "statistical comparisons, outcome measures, and safety findings without adding unsupported claims."
)

MEDICAL_EQUATION_ANALYSIS_SYSTEM = (
    "You are a quantitative biomedical researcher. Explain equations in terms of biomedical variables, "
    "model assumptions, estimators, scoring rules, and how the formula is used in the surrounding study."
)

MEDICAL_GENERIC_ANALYSIS_SYSTEM = (
    "You are a medical content analyst specializing in {content_type}. "
    "Prioritize diagnoses, interventions, cohorts, biomarkers, endpoints, and evidence quality."
)


MEDICAL_VISION_PROMPT = """Please analyze this medical image and return a JSON object with the following structure:

{{
    "detailed_description": "Describe only medically meaningful visual evidence. Mention image type or figure type, anatomical region or study artifact, abnormal findings, quantitative markers if visible, and what claim the figure appears to support. Distinguish observation from interpretation. If the image is a chart or Kaplan-Meier plot, describe cohorts, axes, trends, and outcome implications.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "MedicalVisualEvidence",
        "summary": "One concise sentence describing the key medical evidence and why it matters."
    }}
}}

Medical image details:
- Image Path: {image_path}
- Captions: {captions}
- Footnotes: {footnotes}

Requirements:
- Use standard medical terminology.
- Prefer explicit findings, biomarkers, procedures, anatomy, outcomes, and cohorts.
- If evidence is ambiguous, say so clearly instead of over-claiming.
"""


MEDICAL_VISION_PROMPT_WITH_CONTEXT = """Please analyze this medical image using both the image metadata and the surrounding document context. Return a JSON object with the following structure:

{{
    "detailed_description": "Describe the medically relevant visual evidence and explain how it connects to the surrounding study or clinical discussion. Mention the figure type, anatomical region, measured variable or endpoint, abnormal findings, cohort or treatment comparison, and any outcome or conclusion the figure supports. Keep observation and interpretation clearly separated.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "MedicalVisualEvidence",
        "summary": "One concise sentence summarizing the figure's clinical or scientific role in the surrounding context."
    }}
}}

Context from surrounding content:
{context}

Medical image details:
- Image Path: {image_path}
- Captions: {captions}
- Footnotes: {footnotes}

Requirements:
- Anchor the analysis to the medical context.
- Highlight diagnoses, biomarkers, interventions, cohorts, endpoints, or outcome differences when present.
- If the figure is only illustrative and not evidentiary, say that explicitly.
"""


MEDICAL_TEXT_PROMPT = """Based only on the following medical image metadata, return a JSON object:

{{
    "detailed_description": "Describe the likely medical meaning of the figure using only the provided metadata. State uncertainty explicitly if the metadata is insufficient.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "MedicalVisualEvidence",
        "summary": "One concise sentence describing the likely role of this image in the medical document."
    }}
}}

Medical image metadata:
- Image Path: {image_path}
- Captions: {captions}
- Footnotes: {footnotes}
"""


MEDICAL_TABLE_PROMPT = """Please analyze this clinical or biomedical table and return a JSON object with the following structure:

{{
    "detailed_description": "Summarize the table in terms of study design, cohort characteristics, interventions, comparators, biomarkers, endpoints, adverse events, effect sizes, confidence intervals, p-values, and any medically important differences between groups.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "ClinicalTable",
        "summary": "One concise sentence stating what clinical evidence this table contributes."
    }}
}}

Table details:
- Image Path: {table_img_path}
- Caption: {table_caption}
- Body: {table_body}
- Footnotes: {table_footnote}

Requirements:
- Prioritize medically actionable or study-defining information.
- Prefer explicit numbers and comparisons over vague summaries.
- Mention if the table is descriptive only versus inferential/statistical.
"""


MEDICAL_TABLE_PROMPT_WITH_CONTEXT = """Please analyze this clinical or biomedical table using the surrounding context and return a JSON object with the following structure:

{{
    "detailed_description": "Summarize the table with emphasis on how it supports the surrounding medical argument. Include cohort definitions, treatment arms, biomarkers, endpoints, safety outcomes, statistical significance, and what conclusion the table appears to support.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "ClinicalTable",
        "summary": "One concise sentence describing the role of this table in the surrounding medical context."
    }}
}}

Context from surrounding content:
{context}

Table details:
- Image Path: {table_img_path}
- Caption: {table_caption}
- Body: {table_body}
- Footnotes: {table_footnote}

Requirements:
- Connect the numeric evidence to the nearby medical discussion.
- Call out subgroup comparisons, endpoints, confidence intervals, hazard ratios, odds ratios, p-values, or safety signals when present.
"""


MEDICAL_EQUATION_PROMPT = """Please analyze this biomedical or clinical equation and return a JSON object with the following structure:

{{
    "detailed_description": "Explain what the equation computes, define the variables, identify whether it is a score, model, loss, estimator, risk formula, or physiological relationship, and describe its biomedical purpose.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "BiomedicalEquation",
        "summary": "One concise sentence describing what this equation represents in the medical or biomedical setting."
    }}
}}

Equation details:
- Equation: {equation_text}
- Format: {equation_format}

Requirements:
- Use biomedical or clinical interpretation when possible.
- If the equation is generic mathematics with no clear biomedical meaning, say so explicitly.
"""


MEDICAL_EQUATION_PROMPT_WITH_CONTEXT = """Please analyze this biomedical or clinical equation using the surrounding context and return a JSON object with the following structure:

{{
    "detailed_description": "Explain what the equation computes, define variables in context, identify whether it is a score, model, estimator, survival metric, classifier, physiological equation, or treatment-response formula, and describe how it supports the surrounding medical discussion.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "BiomedicalEquation",
        "summary": "One concise sentence describing the equation's role in the surrounding medical context."
    }}
}}

Context from surrounding content:
{context}

Equation details:
- Equation: {equation_text}
- Format: {equation_format}

Requirements:
- Tie the variables and objective back to the nearby study, diagnosis, biomarker, or endpoint.
- Keep the explanation medically grounded rather than purely mathematical.
"""


MEDICAL_GENERIC_PROMPT = """Please analyze this medical {content_type} content and return a JSON object with the following structure:

{{
    "detailed_description": "Summarize the medically relevant information, including diseases, symptoms, procedures, medications, biomarkers, cohorts, endpoints, outcomes, mechanisms, or evidence claims when present.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "MedicalContent",
        "summary": "One concise sentence stating why this content matters medically."
    }}
}}

Content: {content}

Requirements:
- Focus on clinical or biomedical relevance.
- Ignore decorative or administratively irrelevant details unless they materially affect interpretation.
"""


MEDICAL_GENERIC_PROMPT_WITH_CONTEXT = """Please analyze this medical {content_type} content using the surrounding context and return a JSON object with the following structure:

{{
    "detailed_description": "Summarize the medically relevant content and explain how it supports the surrounding clinical or scientific discussion. Prioritize diagnoses, interventions, biomarkers, cohorts, endpoints, mechanisms, outcomes, and evidence claims.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "MedicalContent",
        "summary": "One concise sentence describing this content's medical role in the surrounding context."
    }}
}}

Context from surrounding content:
{context}

Content: {content}

Requirements:
- Tie the content back to the surrounding study or clinical narrative.
- Prefer medically actionable or evidentiary information over generic prose.
"""


MEDICAL_QUERY_IMAGE_DESCRIPTION = (
    "Describe the medically relevant content of this image. Focus on anatomy, pathology, interventions, cohorts, endpoints, or study conclusions visible in the figure."
)

MEDICAL_QUERY_IMAGE_ANALYST_SYSTEM = (
    "You are a clinician-scientist summarizing medical figures for retrieval and QA."
)

MEDICAL_QUERY_TABLE_ANALYSIS = """Summarize the main clinical or biomedical evidence in this table.

Table data:
{table_data}

Table caption:
{table_caption}

Focus on cohorts, interventions, comparators, biomarkers, endpoints, statistical significance, and safety or efficacy findings.
"""

MEDICAL_QUERY_TABLE_ANALYST_SYSTEM = (
    "You are a medical data analyst summarizing tables for retrieval and question answering."
)

MEDICAL_QUERY_EQUATION_ANALYSIS = """Explain this equation in a biomedical or clinical context.

LaTeX formula:
{latex}

Equation caption:
{equation_caption}

Focus on the variables, the biomedical purpose of the equation, and how it would be used in the study or clinical workflow.
"""

MEDICAL_QUERY_EQUATION_ANALYST_SYSTEM = (
    "You are a quantitative biomedical researcher explaining formulas for retrieval and QA."
)

MEDICAL_QUERY_GENERIC_ANALYSIS = """Summarize the medically relevant content of this {content_type}.

Content:
{content_str}

Focus on diagnoses, interventions, biomarkers, cohorts, endpoints, findings, and evidence claims.
"""

MEDICAL_QUERY_GENERIC_ANALYST_SYSTEM = (
    "You are a medical content analyst summarizing {content_type} for retrieval and QA."
)


MEDICAL_ENTITY_TYPES = [
    "Disease",
    "Symptom",
    "Syndrome",
    "ClinicalSign",
    "Medication",
    "MedicalProcedure",
    "Therapy",
    "Dosage",
    "Anatomy",
    "Gene",
    "Protein",
    "Biomarker",
    "Pathogen",
    "StudyOutcome",
    "Metric",
    "PopulationGroup",
]


MEDICAL_PROMPT_OVERRIDES = {
    "IMAGE_ANALYSIS_SYSTEM": MEDICAL_IMAGE_ANALYSIS_SYSTEM,
    "IMAGE_ANALYSIS_FALLBACK_SYSTEM": MEDICAL_IMAGE_ANALYSIS_FALLBACK_SYSTEM,
    "TABLE_ANALYSIS_SYSTEM": MEDICAL_TABLE_ANALYSIS_SYSTEM,
    "EQUATION_ANALYSIS_SYSTEM": MEDICAL_EQUATION_ANALYSIS_SYSTEM,
    "GENERIC_ANALYSIS_SYSTEM": MEDICAL_GENERIC_ANALYSIS_SYSTEM,
    "vision_prompt": MEDICAL_VISION_PROMPT,
    "vision_prompt_with_context": MEDICAL_VISION_PROMPT_WITH_CONTEXT,
    "text_prompt": MEDICAL_TEXT_PROMPT,
    "table_prompt": MEDICAL_TABLE_PROMPT,
    "table_prompt_with_context": MEDICAL_TABLE_PROMPT_WITH_CONTEXT,
    "equation_prompt": MEDICAL_EQUATION_PROMPT,
    "equation_prompt_with_context": MEDICAL_EQUATION_PROMPT_WITH_CONTEXT,
    "generic_prompt": MEDICAL_GENERIC_PROMPT,
    "generic_prompt_with_context": MEDICAL_GENERIC_PROMPT_WITH_CONTEXT,
    "QUERY_IMAGE_DESCRIPTION": MEDICAL_QUERY_IMAGE_DESCRIPTION,
    "QUERY_IMAGE_ANALYST_SYSTEM": MEDICAL_QUERY_IMAGE_ANALYST_SYSTEM,
    "QUERY_TABLE_ANALYSIS": MEDICAL_QUERY_TABLE_ANALYSIS,
    "QUERY_TABLE_ANALYST_SYSTEM": MEDICAL_QUERY_TABLE_ANALYST_SYSTEM,
    "QUERY_EQUATION_ANALYSIS": MEDICAL_QUERY_EQUATION_ANALYSIS,
    "QUERY_EQUATION_ANALYST_SYSTEM": MEDICAL_QUERY_EQUATION_ANALYST_SYSTEM,
    "QUERY_GENERIC_ANALYSIS": MEDICAL_QUERY_GENERIC_ANALYSIS,
    "QUERY_GENERIC_ANALYST_SYSTEM": MEDICAL_QUERY_GENERIC_ANALYST_SYSTEM,
}
